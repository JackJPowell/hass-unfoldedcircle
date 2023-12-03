"""Platform for Switch integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

# Import the device class from the component that you want to support
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required("pin"): cv.string,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Switch platform."""
    # Setup connection with devices/cloud
    remote = hass.data[DOMAIN][config_entry.entry_id]

    # Verify that passed in configuration works
    if not await remote.can_connect():
        _LOGGER.error("Could not connect to Remote")
        return

    # Get Basic Device Information
    await remote.get_remote_information()
    await remote.get_remote_update_information()
    await remote.get_remote_configuration()

    # Add devices
    await remote.get_activities()
    async_add_entities(UCRemoteSwitch(switch) for switch in remote.activities)


class UCRemoteSwitch(SwitchEntity):
    @property
    def unique_id(self) -> str | None:
        return super().unique_id

    @unique_id.setter
    def unique_id(self, value):
        self._unique_id = value

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.switch.remote.serial_number)
            },
            name=self.switch.remote.name,
            manufacturer=self.switch.remote.manufacturer,
            model=self.switch.remote.model_name,
            sw_version=self.switch.remote.sw_version,
            hw_version=self.switch.remote.hw_revision,
            configuration_url=self.switch.remote.configuration_url,
        )

    """Representation of a Switch."""

    def __init__(self, switch) -> None:
        """Initialize a switch."""
        self.switch = switch
        self._name = f"{self.switch.remote.name} {switch.name}"
        self._attr_name = f"{self.switch.remote.name} {switch.name}"
        self._attr_unique_id = switch._id
        self._state = switch.state
        self.unique_id = self.switch._id
        self._attr_icon = "mdi:remote-tv"

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state == "ON" or self._state == "RUNNING"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the switch to turn on."""
        await self.switch.turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the switch to turn off."""
        await self.switch.turn_off()

    async def async_update(self) -> None:
        """Fetch new state data for this switch.

        This is the only method that should fetch new data for Home Assistant.
        """
        await self.switch.update()
        self._state = self.switch.state
