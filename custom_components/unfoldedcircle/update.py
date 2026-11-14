"""Update sensor."""

import asyncio
from datetime import timedelta
import logging
from typing import Any

from unfurled.helpers.exceptions import HTTPError

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UnfoldedCircleConfigEntry, UnfoldedCircleDockCoordinator
from .entity import UnfoldedCircleDockEntity, UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)

_UPDATE_POLL_INTERVAL = 6
_DOWNLOAD_STALL_TIMEOUT = 300
_DOWNLOAD_TIMEOUT = 1800
_INSTALL_ATTEMPTS = 5


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up platform."""
    coordinator = config_entry.runtime_data.coordinator
    async_add_entities([Update(coordinator)])

    for (
        subentry_id,
        dock_coordinator,
    ) in config_entry.runtime_data.docks.items():
        async_add_entities(
            [
                UpdateDock(
                    dock_coordinator,
                    config_entry,
                    config_entry.subentries[subentry_id],
                )
            ],
            config_subentry_id=subentry_id,
        )


class Update(UnfoldedCircleEntity, UpdateEntity):
    """Update Entity."""

    _attr_icon = "mdi:update"
    _attr_should_poll = True
    SCAN_INTERVAL = timedelta(hours=1)

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_update_status"
        self._attr_name = "Firmware"
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_auto_update = (
            self.coordinator.api.settings.software_update.auto_update
        )
        self._attr_installed_version = self.coordinator.api.device.sw_version
        self._attr_latest_version = (
            self.coordinator.api.system.update_info.latest_version
        )
        self._attr_release_notes = self.coordinator.api.system.update_info.release_notes
        self._attr_entity_category = EntityCategory.CONFIG
        self._download_progress = 0
        self._is_downloading = False
        self._updated_requested = False
        self._download_failed = asyncio.Event()

        self._attr_supported_features = UpdateEntityFeature(
            UpdateEntityFeature.INSTALL
            | UpdateEntityFeature.PROGRESS
            | UpdateEntityFeature.RELEASE_NOTES
        )
        self._attr_title = f"{self.coordinator.api.device.name} Firmware"

    @property
    def update_percentage(self) -> int | float | None:
        """Reserve the first ten percent for downloading the firmware."""
        if not self._updated_requested:
            return None
        return max(
            self._download_progress,
            self.coordinator.api.system.update_info.update_percent,
        )

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Download firmware, then make a bounded attempt to start installation."""
        if (
            self._updated_requested
            or self._is_downloading
            or self.coordinator.api.system.update_info.in_progress
        ):
            return

        self._download_failed.clear()
        self._updated_requested = True
        self._attr_in_progress = True
        self._download_progress = 0
        self._is_downloading = True
        self.async_write_ha_state()
        started = False
        try:
            async with asyncio.timeout(_DOWNLOAD_TIMEOUT):
                await self._async_start_update()
            started = True
        except HTTPError as ex:
            battery_level = self.coordinator.api.state.battery_level
            try:
                battery_percentage = float(battery_level)
            except (TypeError, ValueError):
                battery_percentage = None

            if ex.status_code == 503 and (
                battery_percentage is not None and battery_percentage < 50
            ):
                message = (
                    "Firmware update was rejected because the remote battery is "
                    f"{battery_percentage:g}%. Charge it to at least 50% and try again."
                )
            else:
                message = (
                    "Firmware update failed: the remote returned "
                    f"HTTP status {ex.status_code}."
                )
            _LOGGER.error("Unfolded Circle Update Failed: %s", message)
            raise HomeAssistantError(message) from ex
        except TimeoutError as ex:
            raise HomeAssistantError(
                "Firmware download timed out. Try installing the update again."
            ) from ex
        finally:
            self._is_downloading = False
            if not started:
                self._updated_requested = False
                self._attr_in_progress = False
                self._download_progress = 0
            self.async_write_ha_state()

    async def _async_start_update(self) -> None:
        """Wait for download completion before retrying the install request."""
        try:
            state = await self.coordinator.api.system.update_firmware()
        except HTTPError as ex:
            if ex.status_code not in (409, 422):
                raise
            # An existing download/install must be inspected before another POST.
            state = "DOWNLOAD"

        if state == "START":
            return
        if state == "NO_BATTERY":
            raise HomeAssistantError(
                "Charge the remote to at least 50% before updating."
            )
        if state != "DOWNLOAD":
            raise HomeAssistantError(f"Unexpected firmware update state: {state}.")

        previous_percentage = -1
        stalled_polls = 0
        install_attempts = 0
        while True:
            await self._async_wait_for_download_poll()
            self._raise_if_download_failed()
            status = await self.coordinator.api.system.get_update_status()
            self._raise_if_download_failed()
            progress = status.get("progress", status)
            state = progress.get("state", status.get("state"))
            if state in ("START", "RUN", "PROGRESS", "INSTALLING", "UPDATING"):
                return
            if state in ("FAILURE", "ERROR"):
                raise HomeAssistantError(
                    "The remote reported a firmware download failure."
                )

            percentage = self.update_download_status(status)
            if percentage > previous_percentage:
                stalled_polls = 0
            else:
                stalled_polls += 1
            previous_percentage = percentage
            if stalled_polls * _UPDATE_POLL_INTERVAL >= _DOWNLOAD_STALL_TIMEOUT:
                raise HomeAssistantError("Firmware download stopped making progress.")
            if percentage < 100:
                continue

            # Validation can lag behind the final download event. Retry a few
            # times, tolerating conflicts while the remote finishes validation.
            install_attempts += 1
            try:
                state = await self.coordinator.api.system.update_firmware()
            except HTTPError as ex:
                if ex.status_code not in (409, 422):
                    raise
                state = "DOWNLOAD"
            if state == "START":
                return
            if state == "NO_BATTERY":
                raise HomeAssistantError(
                    "Charge the remote to at least 50% before updating."
                )
            if state != "DOWNLOAD":
                raise HomeAssistantError(f"Unexpected firmware update state: {state}.")
            if install_attempts >= _INSTALL_ATTEMPTS:
                raise HomeAssistantError(
                    "Firmware downloaded, but installation did not start. Try again."
                )

    async def _async_wait_for_download_poll(self) -> None:
        """Wake immediately if a WebSocket event reports download failure."""
        try:
            await asyncio.wait_for(
                self._download_failed.wait(), timeout=_UPDATE_POLL_INTERVAL
            )
        except TimeoutError:
            pass

    def _raise_if_download_failed(self) -> None:
        """Keep a WebSocket failure from being erased by a subsequent poll."""
        if (
            self._download_failed.is_set()
            or self.coordinator.api.system.update_info.download_state == "FAILURE"
        ):
            raise HomeAssistantError("The remote reported a firmware download failure.")

    def update_download_status(self, status: dict) -> int:
        """Publish download progress using the raw response and WebSocket state."""
        progress = status.get("progress", status)
        download_percentage = max(
            progress.get("download_percent", 0) or 0,
            self.coordinator.api.system.update_info.download_percent,
        )
        if progress.get("state") == "DOWNLOADED":
            download_percentage = 100
        self._download_progress = max(
            self._download_progress, min(100, download_percentage) // 10
        )
        self.async_write_ha_state()
        return download_percentage

    async def async_release_notes(self) -> str:
        return self.coordinator.api.system.update_info.release_notes

    async def async_update(self) -> None:
        """Update update information."""
        try:
            await self.coordinator.api.system.force_update_check()
            self._attr_latest_version = (
                self.coordinator.api.system.update_info.latest_version
            )
            self._attr_installed_version = self.coordinator.api.device.sw_version
        except Exception as ex:
            _LOGGER.debug("Failure when checking for update: %s", ex)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        update_info = self.coordinator.api.system.update_info
        if self._updated_requested and update_info.download_state == "FAILURE":
            if self._is_downloading:
                self._download_failed.set()
            _LOGGER.error("The remote reported a firmware download failure.")
            self._updated_requested = False
            self._attr_in_progress = False
            self._download_progress = 0
        if self._updated_requested:
            self._download_progress = max(
                self._download_progress, min(100, update_info.download_percent) // 10
            )
            if update_info.update_percent == 100 or (
                not self._is_downloading
                and not update_info.in_progress
                and self.coordinator.api.device.sw_version == update_info.latest_version
            ):
                self._updated_requested = False
                self._attr_in_progress = False
            else:
                self._attr_in_progress = True
        else:
            self._attr_in_progress = False
        self._attr_installed_version = self.coordinator.api.device.sw_version
        self._attr_latest_version = update_info.latest_version
        self.async_write_ha_state()


class UpdateDock(UnfoldedCircleDockEntity, UpdateEntity):
    """Update Entity."""

    _attr_icon = "mdi:update"
    _attr_should_poll = True
    SCAN_INTERVAL = timedelta(hours=1)

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        config_entry: UnfoldedCircleConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the Update sensor."""
        super().__init__(coordinator, config_entry, subentry)
        self._attr_unique_id = f"{subentry.unique_id}_{coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_update_status"
        self._attr_name = "Firmware"
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_installed_version = self.coordinator.api.device.software_version
        self._attr_latest_version = (
            self.coordinator.api.system.update_info.latest_version
        )
        self._attr_entity_category = EntityCategory.CONFIG
        self._updated_requested = False

        self._attr_supported_features = UpdateEntityFeature(UpdateEntityFeature.INSTALL)
        self._attr_title = f"{self.coordinator.api.device.name} Firmware"

    @property
    def available(self) -> bool:
        """Wait for the dock firmware status to load."""
        return (
            super().available and self.coordinator.api.system.update_info.status_loaded
        )

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        if self.coordinator.api.system.update_info.in_progress is True:
            return

        self._updated_requested = True
        self._attr_in_progress = False
        try:
            update_information = await self.coordinator.api.system.update_firmware()
            if update_information.get("state") == "NO_BATTERY":
                _LOGGER.error(
                    "Unfolded Circle Update Failed -- Please charge the dock before upgrading."
                )
                return

        except HTTPError as ex:
            _LOGGER.error(
                "Unfolded Circle Update Failed ** If 503, battery level < 20 ** Status: %s",
                ex.status_code,
            )

        self._attr_in_progress = True
        self.async_write_ha_state()

    # async def async_release_notes(self) -> str:
    #     return self.coordinator.api.release_notes

    async def async_update(self) -> None:
        """Update update information."""
        try:
            await self.coordinator.api.system.get_update_status()
            self._attr_latest_version = (
                self.coordinator.api.system.update_info.latest_version
            )
            self._attr_installed_version = self.coordinator.api.device.software_version
        except Exception as ex:
            _LOGGER.debug("Failure when checking for dock update: %s", ex)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        update_info = self.coordinator.api.system.update_info
        if (update_info.in_progress is True) and self._updated_requested is True:
            if update_info.update_percent == 0:
                self._attr_in_progress = "0"
            elif update_info.update_percent == 100:
                self._attr_in_progress = update_info.update_percent
                self._updated_requested = False
            else:
                self._attr_in_progress = update_info.update_percent
        else:
            self._attr_in_progress = False
            self._attr_installed_version = self.coordinator.api.device.software_version
            self._attr_latest_version = (
                self.coordinator.api.system.update_info.latest_version
            )
        self.async_write_ha_state()
