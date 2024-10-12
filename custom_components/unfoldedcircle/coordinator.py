"""Coordinator for Unfolded Circle Integration"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.error import HTTPError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from pyUnfoldedCircleRemote.remote import Remote
from pyUnfoldedCircleRemote.remote_websocket import RemoteWebsocket
from pyUnfoldedCircleRemote.dock_websocket import DockWebsocket
from pyUnfoldedCircleRemote.dock import Dock

from .const import DEVICE_SCAN_INTERVAL, DOMAIN, DEBUG_UC_MSG
from .websocket import UCWebsocketClient

_LOGGER = logging.getLogger(__name__)


class UnfoldedCircleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Base Unfolded Circle Coordinator Class"""

    subscribe_events: dict[str, bool]
    entities: list[CoordinatorEntity]
    websocket_client: UCWebsocketClient

    def __init__(self, hass: HomeAssistant, unfolded_circle_device) -> None:
        super().__init__(
            hass,
            name=DOMAIN,
            logger=_LOGGER,
            update_interval=DEVICE_SCAN_INTERVAL,
        )
        self.hass = hass
        self.api: Remote = unfolded_circle_device
        self.data = {}
        self.websocket = None
        self.websocket_task = None
        self.subscribe_events = {}
        self.polling_data = False
        self.entities = []
        self.docks: list[Dock] = []
        self.websocket_client = UCWebsocketClient(hass)

    async def init_websocket(self):
        """Initialize the Web Socket"""
        self.websocket.events_to_subscribe = [
            "software_updates",
            *list(self.subscribe_events.keys()),
        ]
        _LOGGER.debug(
            "Unfolded Circle Remote events list to subscribe %s",
            self.websocket.events_to_subscribe,
        )
        self.websocket_task = asyncio.create_task(
            self.websocket.init_websocket(self.receive_data, self.reconnection_ws)
        )

    def update(self, message: any):
        """Update data received from WS"""
        try:
            # Update internal data from the message
            self.api.update_from_message(message)
            # Trigger update of entities
            self.async_set_updated_data(vars(self.api))
            # asyncio.create_task(self._async_update_data()).result()
        except Exception as ex:
            _LOGGER.error(
                "Unfolded Circle Remote error while updating entities: %s", ex
            )

    async def reconnection_ws(self):
        """Reconnect WS Connection if dropped"""
        _LOGGER.debug(
            "Unfolded Circle Remote coordinator refresh data after a period of disconnection"
        )
        try:
            await self.api.update()
            self.async_set_updated_data(vars(self.api))
        except Exception as ex:
            _LOGGER.error(
                "Unfolded Circle Remote reconnection_ws error while updating entities: %s",
                ex,
            )

    async def receive_data(self, message: any):
        """update coordinator data upon receipt"""
        self.update(message)
        if logging.DEBUG:
            self.debug_structure()

    def debug_structure(self):
        """Output debugbing information"""
        debug_info = []
        for activity_group in self.api.activity_groups:
            debug_info.append(
                f"Activity group {activity_group.name} ({activity_group.id}) :"
            )
            active_media_entity = None
            if active_media_entity is None:
                debug_info.append("  No active media entity for this group")
            for activity in activity_group.activities:
                debug_info.append(
                    f" - Activity {activity.name} ({activity.id}) : {activity.state})"
                )
                for media_entity in activity.mediaplayer_entities:
                    if active_media_entity and active_media_entity == media_entity:
                        debug_info.append(
                            f"   > Media {media_entity.name} ({media_entity.id}) : {media_entity.state}"
                        )
                    else:
                        debug_info.append(
                            f"   - Media {media_entity.name}  ({media_entity.id}) : {media_entity.state}"
                        )
        debug_info.append("Media player entities from remote :")
        for media_entity in self.api._entities:
            debug_info.append(
                f" - Player {media_entity.name} ({media_entity.id}) : {media_entity.state}"
            )
        if DEBUG_UC_MSG:
            _LOGGER.debug("UC debug structure\n%s", "\n".join(debug_info))

    async def _async_update_data(self) -> dict[str, Any]:
        """Get the latest data from the Unfolded Circle Remote."""
        try:
            if self.polling_data:
                await self.api.update()

            self.data = vars(self.api)
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

    # List of events to subscribe to the websocket
    subscribe_events: dict[str, bool]
    entities: list[CoordinatorEntity]

    def __init__(self, hass: HomeAssistant, unfolded_circle_remote_device) -> None:
        """Initialize the Coordinator."""
        super().__init__(hass, unfolded_circle_remote_device)
        self.hass = hass
        self.api: Remote = unfolded_circle_remote_device
        self.data = {}
        self.websocket = RemoteWebsocket(self.api.endpoint, self.api.apikey)
        self.websocket_task = None
        self.subscribe_events = {}
        self.polling_data = False
        self.entities = []
        self.docks: list[Dock] = self.api._docks
        _LOGGER.debug("Unfolded Circle websocket APIs registered")


class UnfoldedCircleDockCoordinator(
    UnfoldedCircleCoordinator, DataUpdateCoordinator[dict[str, Any]]
):
    """Data update coordinator for an Unfolded Circle Remote device."""

    # List of events to subscribe to the websocket
    subscribe_events: dict[str, bool]
    entities: list[CoordinatorEntity]

    def __init__(self, hass: HomeAssistant, dock: Dock) -> None:
        """Initialize the Coordinator."""
        super().__init__(hass, dock)
        self.hass = hass
        self.api: Dock = dock
        self.data = {}
        self.websocket = DockWebsocket(
            self.api._ws_endpoint,
            api_key=dock.apikey,
            dock_password=self.api.password,
        )
        self.websocket_task = None
        self.subscribe_events = {}
        self.polling_data = False
        self.entities = []

        _LOGGER.debug("Unfolded Circle websocket APIs registered")

    async def init_websocket(self):
        """Initialize the Web Socket"""
        self.websocket_task = asyncio.create_task(
            self.websocket.init_websocket(self.receive_data, self.reconnection_ws)
        )

    def debug_structure(self):
        pass
