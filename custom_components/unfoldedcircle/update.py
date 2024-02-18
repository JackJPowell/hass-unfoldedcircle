"""Update sensor."""
import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNFOLDED_CIRCLE_API, UNFOLDED_CIRCLE_COORDINATOR
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up platform."""
    remote = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_API]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    new_devices = []
    new_devices.append(Update(coordinator, remote))
    if new_devices:
        async_add_entities(new_devices)


class Update(UnfoldedCircleEntity, UpdateEntity):
    """Update Entity."""

    _attr_icon = "mdi:update"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._remote.serial_number)
            },
            name=self._remote.name,
            manufacturer=self._remote.manufacturer,
            model=self._remote.model_name,
            sw_version=self._remote.sw_version,
            hw_version=self._remote.hw_revision,
            configuration_url=self._remote.configuration_url,
        )

    def __init__(self, coordinator, remote) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._remote = remote
        self._attr_unique_id = f"{self._remote.name}_update_status"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Firmware"
        self._attr_auto_update = self._remote.automatic_updates
        self._attr_installed_version = self._remote.sw_version
        self._attr_device_class = "firmware"
        self._attr_in_progress = self._remote.update_in_progress

        self._attr_latest_version = self._remote.latest_sw_version
        self._attr_release_url = self._remote.release_notes_url
        self._attr_entity_category = EntityCategory.CONFIG

        # self._attr_state: None = None
        # _attr_release_summary =
        self._attr_supported_features = UpdateEntityFeature(
            0
        )  # UpdateEntityFeature.INSTALL
        self._attr_title = f"{self._remote.name} Firmware"

    @property
    def should_poll(self) -> bool:
        return False

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
        await self._remote.get_remote_update_information()
        self._attr_latest_version = self._remote.latest_sw_version
        self._attr_installed_version = self._remote.sw_version

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update only if activity changed
        self.async_write_ha_state()