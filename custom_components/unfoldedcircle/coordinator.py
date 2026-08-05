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
from pyUnfoldedCircleRemote.remote import Remote
from pyUnfoldedCircleRemote.remote_websocket import RemoteWebsocket
from pyUnfoldedCircleRemote.dock import Dock, HTTPError as DockHTTPError

from .const import (
    DEVICE_SCAN_INTERVAL,
    DOCK_FAILURE_THRESHOLD,
    DOCK_SCAN_INTERVAL,
    DOMAIN,
)
from .helpers import (
    async_create_issue_dock_unreachable,
    async_delete_issue_dock_unreachable,
)
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
            s.strip() for s in initial_events.split(",") if s.strip()
        ] + list(self.subscribe_events.keys())
        _LOGGER.debug(
            "Unfolded Circle Remote events list to subscribe %s",
            self.websocket.events_to_subscribe,
        )
        self.websocket_task = asyncio.create_task(
            self.websocket.init_websocket(self.receive_data, self.reconnection_ws)
        )

    async def reconnection_ws(self):
        """Reconnect WS Connection if dropped"""
        _LOGGER.warning(
            "Unfolded Circle Remote websocket reconnected - starting full data refresh to resync state"
        )
        try:
            await self.api.update()
            self.async_set_updated_data(vars(self.api))
            _LOGGER.warning(
                "Unfolded Circle Remote full data refresh completed successfully after websocket reconnection"
            )
        except Exception as ex:
            _LOGGER.error(
                "Unfolded Circle Remote FAILED to refresh data after websocket reconnection: %s. Data may be stale.",
                ex,
                exc_info=True,
            )

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
        if initial_events:
            initial_events = f",{initial_events}"
        await super().init_websocket(f"software_updates,docks,emitters{initial_events}")


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
        # Unlike the remote, a dock has no websocket feeding this coordinator
        # (init_websocket below is a no-op). Without polling, the dock is only
        # ever contacted once, during setup: a dock that goes offline afterwards
        # stays invisible because its entities keep serving their last known
        # values. Polling on a slower schedule than the remote makes the dock's
        # reachability observable without adding much traffic.
        self.update_interval = DOCK_SCAN_INTERVAL
        self._consecutive_failures = 0
        # Guards against re-reporting an outage on every poll: creating the
        # repair issue also logs a warning.
        self._unreachable_reported = False

    async def init_websocket(self, initial_events: str = ""):
        """Initialize the Web Socket"""
        pass

    async def update_data(self) -> dict[str, Any]:
        """Poll the dock, keeping its repair issue in sync with reachability."""
        try:
            # The full update() is used rather than only get_info(): it also
            # refreshes the update status that UpdateDock seeds its versions
            # from. Without it, latest_version stays empty and the entity
            # reports a firmware update that does not exist.
            await self.api.update()
        except DockHTTPError as ex:
            # The remote answered but reported that it cannot reach the dock
            # ("503 Connection to dock not established"), so the dock really is
            # the faulty part here and it is worth raising a repair issue for.
            return self._async_handle_failed_poll(ex, dock_at_fault=True)
        except Exception as ex:
            # The remote itself did not answer. Dock requests travel through the
            # remote, and the remote sleeps a few minutes after it stops
            # charging, so this also happens during entirely normal use. The
            # dock entities still become unavailable, since they really cannot
            # be reached, but a "dock unreachable" repair would blame the wrong
            # device for something that resolves itself once the remote wakes.
            return self._async_handle_failed_poll(ex, dock_at_fault=False)

        self._consecutive_failures = 0
        # Deleting an unknown issue is a documented no-op, so this also clears an
        # issue raised before a reload, when this instance never saw the failure.
        self._unreachable_reported = False
        async_delete_issue_dock_unreachable(self.hass, self.api.id)
        return vars(self.api)

    def _async_handle_failed_poll(
        self, ex: Exception, dock_at_fault: bool
    ) -> dict[str, Any]:
        """Account for a failed poll, tolerating a single miss.

        Returns the previous data while the failure is still within the
        tolerance, and raises UpdateFailed once it is not.
        """
        self._consecutive_failures += 1
        # A single miss is usually a slow answer rather than a real outage: the
        # library allows five seconds per call. Keep serving the previous data
        # until two polls in a row fail, so one slow response does not flip
        # every entity to unavailable and raise a repair issue that clears
        # moments later.
        if (
            self._consecutive_failures < DOCK_FAILURE_THRESHOLD
            and self.data is not None
        ):
            _LOGGER.debug(
                "Dock %s did not answer, waiting for the next poll: %s",
                self.api.name,
                ex,
            )
            return self.data

        if dock_at_fault and not self._unreachable_reported:
            self._unreachable_reported = True
            async_create_issue_dock_unreachable(
                self.hass, self.api, self.config_entry, self.subentry, ex
            )
        raise UpdateFailed(
            f"Error communicating with Unfolded Circle dock {self.api.name}: {ex}"
        ) from ex
