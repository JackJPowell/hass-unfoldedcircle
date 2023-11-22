"""Button for Unfolded Circle"""
from typing import Any
import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

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
    new_devices.append(Button(remote))
    if new_devices:
        async_add_entities(new_devices)


class Button(ButtonEntity):
    """Representation of a Button entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = ButtonDeviceClass.RESTART

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

    def __init__(self, remote):
        """Initialize the sensor."""
        self._remote = remote
        self._attr_unique_id = f"{self._remote.serial_number}_restart_button"
        self._attr_name = f"{self._remote.name} Restart Remote"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._remote._online

    async def async_press(self) -> None:
        """Press the button."""
        await self._remote.post_system_command("RESTART")
