"""WebSocket client layer for Unfolded Circle devices.

Provides:
- ``WebSocketClient`` - base class with auto-reconnect, callback dispatch.
- ``RemoteWebSocketClient`` - connects to the remote using an API key.
- ``DockWebSocketClient`` - connects to the dock using a password/token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any
from urllib.parse import urlparse

import websockets
from websockets.exceptions import ConnectionClosed

_LOGGER = logging.getLogger(__name__)

_RECONNECT_DELAY = 10.0  # seconds
_PING_INTERVAL = 30
_PING_TIMEOUT = 30
_CLOSE_TIMEOUT = 20

MessageCallback = Callable[[str], Coroutine[Any, Any, None]]
ConnectCallback = Callable[[], Coroutine[Any, Any, None]]


class WebSocketClient:
    """Auto-reconnecting WebSocket client with a callback-based event model.

    Subclasses override :meth:`_extra_connect_headers` and
    :meth:`_on_connected` to perform device-specific handshake.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        reconnect_delay: float = _RECONNECT_DELAY,
    ) -> None:
        self._endpoint = endpoint
        self._reconnect_delay = reconnect_delay
        self._ws: Any = None  # websockets connection
        self._task: asyncio.Task | None = None
        self._running = False

        self._message_callbacks: list[MessageCallback] = []
        self._connect_callbacks: list[ConnectCallback] = []
        self._disconnect_callbacks: list[ConnectCallback] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_message(self, callback: MessageCallback) -> None:
        """Register a coroutine to be called with each raw message string."""
        self._message_callbacks.append(callback)

    def on_connect(self, callback: ConnectCallback) -> None:
        """Register a coroutine to be called on every *re*-connection."""
        self._connect_callbacks.append(callback)

    def on_disconnect(self, callback: ConnectCallback) -> None:
        """Register a coroutine to be called when the connection is lost."""
        self._disconnect_callbacks.append(callback)

    async def connect(self) -> None:
        """Start the background connection loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"ws-{self._endpoint}")

    async def disconnect(self) -> None:
        """Gracefully stop the connection loop."""
        self._running = False
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def send(self, payload: dict | str) -> None:
        """Send a message over the current connection.

        Safe to call from any task.  Silently drops if not connected.
        """
        if not self._ws:
            _LOGGER.debug("ws send ignored - not connected (%s)", self._endpoint)
            return
        message = json.dumps(payload) if isinstance(payload, dict) else payload
        try:
            await self._ws.send(message)
        except Exception as exc:
            _LOGGER.warning("ws send failed: %s", exc)

    @property
    def is_connected(self) -> bool:
        """``True`` if currently connected."""
        return self._ws is not None and not self._ws.closed

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        first = True
        while self._running:
            try:
                _LOGGER.debug("ws connecting → %s", self._endpoint)
                async with websockets.connect(
                    self._endpoint,
                    additional_headers=self._extra_connect_headers(),
                    ping_interval=_PING_INTERVAL,
                    ping_timeout=_PING_TIMEOUT,
                    close_timeout=_CLOSE_TIMEOUT,
                ) as ws:
                    self._ws = ws
                    _LOGGER.debug("ws connected → %s", self._endpoint)

                    if not first:
                        for conn_cb in self._connect_callbacks:
                            asyncio.create_task(conn_cb())
                    first = False

                    await self._on_connected(ws)

                    async for message in ws:
                        raw = message if isinstance(message, str) else message.decode()
                        for msg_cb in self._message_callbacks:
                            asyncio.create_task(msg_cb(raw))

            except ConnectionClosed as exc:
                _LOGGER.debug("ws closed (%s): %s", self._endpoint, exc)
            except OSError as exc:
                _LOGGER.debug("ws OS error (%s): %s", self._endpoint, exc)
            except Exception as exc:
                _LOGGER.error("ws unexpected error (%s): %s", self._endpoint, exc)
            finally:
                self._ws = None
                for disc_cb in self._disconnect_callbacks:
                    asyncio.create_task(disc_cb())

            if self._running:
                _LOGGER.debug(
                    "ws reconnecting in %.0fs → %s",
                    self._reconnect_delay,
                    self._endpoint,
                )
                await asyncio.sleep(self._reconnect_delay)

        _LOGGER.debug("ws loop exited → %s", self._endpoint)

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def _extra_connect_headers(self) -> dict[str, str]:
        """Return additional HTTP headers for the upgrade request."""
        return {}

    async def _on_connected(self, ws: Any) -> None:
        """Called immediately after a successful connection.

        Override to perform device-specific subscriptions or authentication.
        """


class RemoteWebSocketClient(WebSocketClient):
    """WebSocket client for the Unfolded Circle remote.

    Authenticates via the ``API-KEY`` header and automatically subscribes
    to all event channels on connection.
    """

    _SUBSCRIBE_ALL = {
        "id": 1,
        "kind": "req",
        "msg": "subscribe_events",
        "msg_data": {"channels": ["all"]},
    }

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        reconnect_delay: float = _RECONNECT_DELAY,
    ) -> None:
        parsed = urlparse(api_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        endpoint = f"{scheme}://{parsed.netloc}/ws"
        super().__init__(endpoint, reconnect_delay=reconnect_delay)
        self._api_key = api_key

    def _extra_connect_headers(self) -> dict[str, str]:
        return {"API-KEY": self._api_key}

    async def _on_connected(self, ws: Any) -> None:
        await self.send(self._SUBSCRIBE_ALL)


class DockWebSocketClient(WebSocketClient):
    """WebSocket client for an Unfolded Circle dock.

    The dock uses a token/password-based auth flow: the server sends an
    ``auth_required`` message; we reply with the password.
    """

    def __init__(
        self,
        ws_url: str,
        password: str,
        *,
        reconnect_delay: float = _RECONNECT_DELAY,
    ) -> None:
        super().__init__(ws_url, reconnect_delay=reconnect_delay)
        self._password = password
        # Subscribe to all dock events after auth
        self._subscribe_payload = {
            "id": 1,
            "kind": "req",
            "msg": "subscribe_events",
            "msg_data": {"channels": ["all"]},
        }

    async def _on_connected(self, ws: Any) -> None:
        """Handle the dock auth handshake before forwarding messages."""
        # The dock may send auth_required as its first message
        try:
            first_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(first_msg)
            if data.get("type") == "auth_required":
                await self.send({"type": "auth", "token": self._password})
        except TimeoutError:
            pass  # no auth challenge - proceed
        except Exception:
            pass

        # Now subscribe
        await self.send(self._subscribe_payload)

    @classmethod
    async def validate(
        cls,
        ws_url: str,
        password: str,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """Test whether *password* is accepted by the dock.

        Opens a short-lived WebSocket connection, performs the auth
        handshake, and returns ``True`` if the dock accepts the password or
        does not require one.  Returns ``False`` on auth failure or if the
        connection cannot be established.

        Args:
            ws_url: The dock's WebSocket endpoint URL.
            password: The password/token to test.
            timeout: Maximum seconds to wait for each handshake step.
        """
        try:
            async with websockets.connect(
                ws_url,
                ping_interval=None,
                close_timeout=3,
            ) as ws:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    data = json.loads(raw)
                except (TimeoutError, Exception):
                    data = {}

                if data.get("type") == "auth_required":
                    await ws.send(json.dumps({"type": "auth", "token": password}))
                    try:
                        raw2 = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        resp = json.loads(raw2)
                        return resp.get("type") != "auth_invalid"
                    except (TimeoutError, Exception):
                        return False
                # No auth challenge — connection accepted without password
                return True
        except Exception:
            return False
