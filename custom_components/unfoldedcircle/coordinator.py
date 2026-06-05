"""Coordinator for Unfolded Circle Integration"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from unfurled.remote import Remote
from unfurled.dock import Dock
from unfurled.helpers.exceptions import HTTPError

from .const import DEVICE_SCAN_INTERVAL, DOMAIN
from .websocket import UCWebsocketClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnfoldedCircleRuntimeData:
    """Unfolded Circle Runtime Data"""

    coordinator: UnfoldedCircleRemoteCoordinator
    remote: Remote
    docks: dict[str, UnfoldedCircleDockCoordinator]


type UnfoldedCircleConfigEntry = ConfigEntry[UnfoldedCircleRuntimeData]


class UnfoldedCircleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Base Unfolded Circle Coordinator Class"""

    entities: list[CoordinatorEntity]
    websocket_client: UCWebsocketClient

    def __init__(
        self,
        hass: HomeAssistant,
        UCDevice: Remote | Dock,
        config_entry: UnfoldedCircleConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            name=DOMAIN,
            logger=_LOGGER,
            update_interval=DEVICE_SCAN_INTERVAL,
            config_entry=config_entry,
            update_method=self.update_data,
        )
        self.hass = hass
        self.api = UCDevice
        self.polling_data = False
        self.entities = []
        self.docks: list[Dock] = []
        self.websocket_client = UCWebsocketClient(hass)

    async def init_websocket(self):
        """Initialize the WebSocket connection."""

    async def update_data(self) -> dict[str, Any]:
        """Get the latest data from the Unfolded Circle device."""
        try:
            if self.polling_data:
                await self.api.update()
            return {"updated": True}
        except HTTPError as err:
            if err.status_code == 401:
                raise ConfigEntryAuthFailed(err) from err
            raise UpdateFailed(
                f"Error communicating with Unfolded Circle API: {err}"
            ) from err
        except Exception as ex:
            raise UpdateFailed(
                f"Error communicating with Unfolded Circle API: {ex}"
            ) from ex

    async def close_websocket(self):
        """Close WebSocket connection."""


class UnfoldedCircleRemoteCoordinator(
    UnfoldedCircleCoordinator, DataUpdateCoordinator[dict[str, Any]]
):
    """Data update coordinator for an Unfolded Circle Remote device."""

    def __init__(
        self,
        hass: HomeAssistant,
        UCRemote: Remote,
        config_entry: UnfoldedCircleConfigEntry,
    ) -> None:
        """Initialize the Coordinator."""
        super().__init__(hass, UCRemote, config_entry)
        self.docks: list[Dock] = self.api.docks

    async def init_websocket(self):
        """Start the unfurled WebSocket and register a state-change callback."""
        self.api.on_state_change(self._on_remote_state_change)
        try:
            await self.api.connect_websocket()
            _LOGGER.debug("Unfolded Circle Remote WebSocket connected")
        except Exception as ex:
            _LOGGER.warning(
                "Unfolded Circle Remote WebSocket failed to connect: %s. "
                "Real-time updates will be unavailable until the next poll.",
                ex,
            )

    async def _on_remote_state_change(self) -> None:
        """Trigger a coordinator update whenever the remote's state changes via WS."""
        self.async_set_updated_data({"updated": True})

    async def close_websocket(self):
        """Disconnect the WebSocket."""
        try:
            await self.api.disconnect_websocket()
        except Exception as ex:
            _LOGGER.error("Error closing Remote WebSocket: %s", ex)


class UnfoldedCircleDockCoordinator(
    UnfoldedCircleCoordinator, DataUpdateCoordinator[dict[str, Any]]
):
    """Data update coordinator for an Unfolded Circle Dock."""

    def __init__(
        self,
        hass: HomeAssistant,
        dock: Dock,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the Coordinator."""
        super().__init__(hass, dock, config_entry=entry)
        self.subentry = subentry

    async def update_data(self) -> dict[str, Any]:
        """Refresh dock state."""
        try:
            await self.api.update()
            return {"updated": True}
        except Exception as ex:
            raise UpdateFailed(
                f"Error communicating with Unfolded Circle Dock: {ex}"
            ) from ex

    async def init_websocket(self):
        """Connect to the dock's native WebSocket for real-time updates."""
        password = self.subentry.data.get("password", "")
        if not password or not self.api.ws_url:
            return
        try:
            await self.api.connect_websocket(
                password=password,
                message_callback=self._on_dock_message,
            )
            _LOGGER.debug(
                "Unfolded Circle Dock WebSocket connected for %s", self.api.device.name
            )
        except Exception as ex:
            _LOGGER.warning(
                "Dock WebSocket connection failed for %s: %s. "
                "Falling back to polling only.",
                self.api.device.name,
                ex,
            )

    async def _on_dock_message(self, raw: str) -> None:
        """Trigger a coordinator update after a dock WS message is processed."""
        self.async_set_updated_data({"updated": True})

    async def close_websocket(self):
        """Disconnect the dock WebSocket."""
        try:
            await self.api.disconnect_websocket()
        except Exception as ex:
            _LOGGER.error("Error closing Dock WebSocket: %s", ex)
