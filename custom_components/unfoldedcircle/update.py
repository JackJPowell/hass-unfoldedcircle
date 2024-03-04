"""Update sensor."""

import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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

        # The name of the entity
        self._attr_name = f"{self.coordinator.api.name} Firmware"
        self._attr_auto_update = self.coordinator.api.automatic_updates
        self._attr_installed_version = self.coordinator.api.sw_version
        self._attr_device_class = "firmware"
        self._attr_in_progress = self.coordinator.api.update_in_progress

        self._attr_latest_version = self.coordinator.api.latest_sw_version
        self._attr_release_url = self.coordinator.api.release_notes_url
        self._attr_entity_category = EntityCategory.CONFIG

        # self._attr_state: None = None
        # _attr_release_summary =
        self._attr_supported_features = UpdateEntityFeature(
            0
        )  # UpdateEntityFeature.INSTALL
        self._attr_title = f"{self.coordinator.api.name} Firmware"

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update.

        Version can be specified to install a specific version. When `None`, the
        latest version needs to be installed.

        The backup parameter indicates a backup should be taken before
        installing the update.
        """
        # if self._remote.update_in_progress == True:
        #     return
        # self._attr_in_progress = True
        # while self._remote.update_in_progress == True:
        #     info = await self._remote.get_update_status()
        #     self._attr_info.get("current_percent")
        # self._attr_installed_version = "1.4.6"
        # self._attr_in_progress = False

    async def async_update(self) -> None:
        """Update update information."""
        await self.coordinator.api.get_remote_update_information()
        self._attr_latest_version = self.coordinator.api.latest_sw_version
        self._attr_installed_version = self.coordinator.api.sw_version

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update only if activity changed
        self._attr_latest_version = self.coordinator.api.latest_sw_version
        self._attr_installed_version = self.coordinator.api.sw_version
        self.async_write_ha_state()
