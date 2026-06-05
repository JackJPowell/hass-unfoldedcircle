"""Zeroconf-based discovery for Unfolded Circle devices."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field

from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

_LOGGER = logging.getLogger(__name__)

_SERVICE_TYPE = "_uc-remote._tcp.local."
_DEFAULT_TIMEOUT = 5.0


@dataclass
class DiscoveredDevice:
    """A device found via Zeroconf."""

    name: str
    host: str
    port: int
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        """Base URL for the remote's REST API (e.g. ``http://""{host}:{port}/api/``)."""
        return f"http://{self.host}:{self.port}/api/"


async def discover_remotes(
    timeout: float = _DEFAULT_TIMEOUT,
) -> list[DiscoveredDevice]:
    """Async Zeroconf discovery for Unfolded Circle remotes.

    Args:
        timeout: How long (seconds) to listen for announcements.

    Returns:
        List of :class:`DiscoveredDevice` instances found on the network.
    """
    found: list[DiscoveredDevice] = []

    async with AsyncZeroconf() as azc:

        def _on_service_state_change(
            zeroconf: Zeroconf,
            service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change is ServiceStateChange.Added:
                info = zeroconf.get_service_info(service_type, name)
                if info and info.addresses:
                    host = socket.inet_ntoa(info.addresses[0])
                    port = info.port or 80
                    props: dict[str, str] = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else (v or "")
                        )
                        for k, v in (info.properties or {}).items()
                    }
                    device = DiscoveredDevice(
                        name=name,
                        host=host,
                        port=port,
                        properties=props,
                    )
                    _LOGGER.debug("Discovered: %s @ %s:%d", name, host, port)
                    found.append(device)

        browser = ServiceBrowser(azc.zeroconf, _SERVICE_TYPE, handlers=[_on_service_state_change])
        await asyncio.sleep(timeout)
        browser.cancel()

    return found


def discover_remotes_sync(timeout: float = _DEFAULT_TIMEOUT) -> list[DiscoveredDevice]:
    """Synchronous wrapper around :func:`discover_remotes`.

    Suitable for use in non-async contexts.
    """
    return asyncio.run(discover_remotes(timeout))
