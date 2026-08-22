from __future__ import annotations

from io import BytesIO
import logging
import secrets
from threading import Lock
from urllib.parse import urljoin, urlparse

from aiohttp import web
from PIL import Image, ImageFile, UnidentifiedImageError

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

FROM_MAX_BYTES = 5_000_000
MAX_SIZE = 512

_LOGGER = logging.getLogger(__name__)
_IMAGE_LOAD_LOCK = Lock()


class ImageProxy:
    """Proxy and resize media artwork for remote clients."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._sources: dict[str, str] = {}
        self._bytes: dict[str, bytes] = {}

    def url_for(self, source: str) -> str:
        """Return an opaque URL for a source image."""
        for token, existing in self._sources.items():
            if existing == source:
                break
        else:
            token = secrets.token_urlsafe(32)
            self._sources[token] = source
        return urljoin(get_url(self.hass), f"/api/unfoldedcircle/image/{token}")

    async def async_get_image(self, token: str) -> bytes:
        if token in self._bytes:
            return self._bytes[token]
        source = self._sources.get(token)
        if source is None:
            raise web.HTTPNotFound()
        parsed = urlparse(source)
        if parsed.scheme not in ("", "http", "https"):
            raise web.HTTPBadRequest()
        # Artwork advertised by Home Assistant normally uses a relative URL.
        # Fetch it via the HA loopback listener: configured internal/external URLs
        # may point through a proxy or public address that HA cannot reach itself.
        is_home_assistant_resource = not parsed.scheme
        if is_home_assistant_resource:
            if self.hass.config.api is None:
                raise web.HTTPServiceUnavailable()
            scheme = "https" if self.hass.config.api.use_ssl else "http"
            base_url = f"{scheme}://127.0.0.1:{self.hass.config.api.port}"
            url = urljoin(base_url, source)
        else:
            url = source
        session = async_get_clientsession(
            self.hass, verify_ssl=not is_home_assistant_resource
        )
        async with session.get(url, timeout=10) as response:
            response.raise_for_status()
            if response.content_length and response.content_length > FROM_MAX_BYTES:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=FROM_MAX_BYTES, actual_size=response.content_length
                )
            raw = await response.content.read(FROM_MAX_BYTES + 1)
        if len(raw) > FROM_MAX_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=FROM_MAX_BYTES, actual_size=len(raw)
            )
        resized = await self.hass.async_add_executor_job(self._resize, raw)
        self._bytes[token] = resized
        return resized

    @staticmethod
    def _resize(raw: bytes) -> bytes:
        # Some artwork providers return images missing a final byte. Pillow can
        # safely decode these, but only when explicitly allowed to do so.
        with _IMAGE_LOAD_LOCK:
            load_truncated_images = ImageFile.LOAD_TRUNCATED_IMAGES
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            try:
                with Image.open(BytesIO(raw)) as image:
                    image.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
                    out = BytesIO()
                    image.convert("RGB").save(
                        out, format="JPEG", quality=95, optimize=True
                    )
                    return out.getvalue()
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("Invalid image") from exc
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = load_truncated_images


class ImageProxyView(HomeAssistantView):
    """Unauthenticated very-narrow view protected by random tokens."""

    url = "/api/unfoldedcircle/image/{token}"
    name = "api:unfoldedcircle:image"
    requires_auth = False

    def __init__(self, proxy: ImageProxy) -> None:
        self.proxy = proxy

    async def get(self, request: web.Request, token: str) -> web.Response:
        try:
            image = await self.proxy.async_get_image(token)
        except web.HTTPException:
            raise
        except Exception as exc:
            _LOGGER.exception("Unable to fetch or resize proxied media artwork")
            raise web.HTTPBadGateway() from exc
        return web.Response(body=image, content_type="image/jpeg")


def get_image_proxy(hass: HomeAssistant) -> ImageProxy:
    key = "unfoldedcircle_image_proxy"
    if (proxy := hass.data.get(key)) is None:
        proxy = ImageProxy(hass)
        hass.http.register_view(ImageProxyView(proxy))
        hass.data[key] = proxy
    return proxy
