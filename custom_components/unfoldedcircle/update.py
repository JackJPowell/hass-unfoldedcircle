"""Update sensor."""

import logging
import math
import time
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyUnfoldedCircleRemote.remote import HTTPError

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    async_add_entities([Update(coordinator)])


class Update(UnfoldedCircleEntity, UpdateEntity):
    """Update Entity."""

    _attr_icon = "mdi:update"

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.name}_update_status"
        self._attr_name = f"{self.coordinator.api.name} Firmware"
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_auto_update = self.coordinator.api.automatic_updates
        self._attr_installed_version = self.coordinator.api.sw_version
        self._attr_latest_version = self.coordinator.api.latest_sw_version
        self._attr_release_notes = self.coordinator.api.release_notes
        self._attr_entity_category = EntityCategory.CONFIG
        self._download_progress = 0

        self._attr_supported_features = UpdateEntityFeature(
            UpdateEntityFeature.INSTALL
            | UpdateEntityFeature.PROGRESS
            | UpdateEntityFeature.RELEASE_NOTES
        )
        self._attr_title = f"{self.coordinator.api.name} Firmware"

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        if self.coordinator.api.update_in_progress is True:
            return

        self._attr_in_progress = False
        self._download_progress = 0
        previous_download_percentage = 0
        retry_count = 0
        try:
            update_information = await self.coordinator.api.update_remote()

            # If the firmware hasn't been downloaded yet, the above request will
            # download it rather than updating the firmware and return a DOWNLOAD
            # status code. Wait 10 seconds for the download to complete and call
            # the update routine again. If download has completed, the upgrade
            # will begin. In between check on download status. If it is progressing
            # keep trying. If not, give it 3 times (30 seconds) before timing out.
            while update_information.get("state") != "START" and retry_count < 6:
                time.sleep(5)
                download_percentage = await self.update_download_status()
                if download_percentage == previous_download_percentage:
                    retry_count = retry_count + 1

                _LOGGER.debug(
                    "Firmware download retry count: %s, update info: %s download percentage: %s",
                    retry_count,
                    update_information,
                    download_percentage,
                )

                update_information = await self.coordinator.api.update_remote()

            if update_information.get("state") == "START":
                # We have started the actual udpate, so set in_progress to String "0"
                # If we previously needed to download the firmware, preserve download
                # percentage so we don't show negative progress.
                self._attr_in_progress = "0"  # Starts progress bar unlike when True
                if self._download_progress > 0:
                    self._attr_in_progress = self._download_progress

        except HTTPError as ex:
            _LOGGER.error(
                "Unfolded Circle Update Failed ** If 503, battery level < 50 ** Status: %s",
                ex.status_code,
            )

        self.async_write_ha_state()

    async def update_download_status(self) -> int:
        """Calls system/update/latest to retrieve current download / udpate status"""
        status_information = await self.coordinator.api.get_update_status()
        download_percentage = status_information.get("download_percent")

        # Unsure if download percentage stays at 100 post download
        if status_information.get("state") == "DOWNLOADED":
            download_percentage = 100

        self._download_progress = math.ceil(download_percentage / 10)
        self._attr_in_progress = self._download_progress
        self.async_write_ha_state()
        return download_percentage

    async def async_release_notes(self) -> str:
        return self.coordinator.api.release_notes

    async def async_update(self) -> None:
        """Update update information."""
        await self.coordinator.api.get_remote_update_information()
        self._attr_latest_version = self.coordinator.api.latest_sw_version
        self._attr_installed_version = self.coordinator.api.sw_version

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.api.update_in_progress is True:
            # If a download was needed, continue to show that percent
            # until the actual update percent exceeds it
            if self._download_progress > self.coordinator.api.update_percent:
                self._attr_in_progress = self._download_progress
            else:
                if self.coordinator.api.update_percent == 0:
                    # 0 is interpreted as false. "0" display progress bar
                    self._attr_in_progress = "0"
                else:
                    self._attr_in_progress = self.coordinator.api.update_percent
        else:
            self._attr_in_progress = False
            self._attr_installed_version = self.coordinator.api.sw_version
            self._attr_latest_version = self.coordinator.api.latest_sw_version
        self.async_write_ha_state()
