"""Coordinator for Unfolded Circle Integration"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from .pyUnfoldedCircleRemote.remote import Remote
from .pyUnfoldedCircleRemote.remote_websocket import RemoteWebsocket
from .pyUnfoldedCircleRemote.dock import Dock

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

    subscribe_events: dict[str, bool]
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
        self.websocket: RemoteWebsocket = None
        self.websocket_task = None
        self.subscribe_events = {}
        self.polling_data = False
        self.entities = []
        self.docks: list[Dock] = []
        self.websocket_client = UCWebsocketClient(hass)

    async def init_websocket(self, initial_events: str):
        """Initialize the Web Socket"""
        self.websocket = RemoteWebsocket(self.api.endpoint, self.api.apikey)
        self.websocket.events_to_subscribe = [
            initial_events,
            *list(self.subscribe_events.keys()),
        ]
        _LOGGER.debug(
            "Unfolded Circle Remote events list to subscribe %s",
            self.websocket.events_to_subscribe,
        )
        self.websocket_task = asyncio.create_task(
            self.websocket.init_websocket(self.receive_data, self.reconnection_ws)
        )

    async def reconnection_ws(self):
        """Reconnect WS Connection if dropped"""
        _LOGGER.debug("Refreshing after ws connection was lost")
        try:
            await self.api.update()
            self.async_set_updated_data(vars(self.api))
        except Exception as ex:
            _LOGGER.error("reconnection_ws error while updating: %s", ex)

    async def receive_data(self, message: any):
        """Update data received from WS"""
        try:
            self.api.update_from_message(message)
            self.async_set_updated_data(vars(self.api))
        except Exception as ex:
            _LOGGER.error("Remote error while updating entities: %s", ex)

    async def update_data(self) -> dict[str, Any]:
        """Get the latest data from the Unfolded Circle Remote."""
        try:
            if self.polling_data:
                await self.api.update()

            return vars(self.api)
        except HTTPError as err:
            if err.status_code == 401:
                raise ConfigEntryAuthFailed(err) from err
            raise UpdateFailed(
                f"Error communicating with Unfolded Circle Remote API {err}"
            ) from err
        except Exception as ex:
            raise UpdateFailed(
                f"Error communicating with Unfolded Circle Remote API {ex}"
            ) from ex

    async def close_websocket(self):
        """Close websocket"""
        try:
            if self.websocket_task:
                self.websocket_task.cancel()
            if self.websocket:
                await self.websocket.close_websocket()
        except Exception as ex:
            _LOGGER.error("Unfolded Circle Remote while closing websocket: %s", ex)


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
        self.websocket = RemoteWebsocket(self.api.endpoint, self.api.apikey)
        self.docks: list[Dock] = self.api._docks

    async def init_websocket(self, initial_events: str = ""):
        """Initialize the Web Socket"""
        await super().init_websocket("software_updates")


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

    async def init_websocket(self, initial_events: str = ""):
        """Initialize the Web Socket"""
        pass
