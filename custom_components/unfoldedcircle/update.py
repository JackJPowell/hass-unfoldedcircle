"""Update sensor."""
from typing import Any
import logging

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

from homeassistant.components.update.const import UpdateEntityFeature

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    remote = hass.data[DOMAIN][config_entry.entry_id]

    # Verify that passed in configuration works
    if not await remote.can_connect():
        _LOGGER.error("Could not connect to Remote")
        return

    # Get Basic Device Information
    await remote.update()

    new_devices = []
    new_devices.append(Update(remote))
    if new_devices:
        async_add_entities(new_devices)


class Update(UpdateEntity):
    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor

    def __init__(self, remote):
        """Initialize the sensor."""
        self._remote = remote

        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.name}_update_status"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Update"
        self._attr_auto_update = self._remote.automatic_updates
        self._attr_installed_version = self._remote.sw_version
        self._attr_device_class = "firmware"
        self._attr_in_progress = self._remote.update_in_progress

        self._attr_latest_version = self._remote.latest_sw_version
        self._attr_release_url = self._remote.release_notes_url

        # self._attr_state: None = None
        # _attr_release_summary = #TODO
        self._attr_supported_features = UpdateEntityFeature(
            0
        )  # UpdateEntityFeature.INSTALL
        self._attr_title = f"{self._remote.name} Firmware"

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
        await self._remote.get_remote_update_information()
