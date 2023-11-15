"""Binary sensor platform for mobile_app."""
from typing import Any
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

from homeassistant.const import (
    ATTR_BATTERY_CHARGING,
)

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
    new_devices.append(BinarySensor(remote))
    if new_devices:
        async_add_entities(new_devices)


class BinarySensor(BinarySensorEntity):
    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = ATTR_BATTERY_CHARGING

    def __init__(self, remote):
        """Initialize the sensor."""
        self._remote = remote

        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_charging_status"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Charging Status"

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        return self._remote.is_charging

    async def async_update(self) -> None:
        await self._remote.update()

    # async def async_restore_last_state(self, last_state):
    #     """Restore previous state."""

    #     await super().async_restore_last_state(last_state)
    #     self._config[ATTR_SENSOR_STATE] = last_state.state == STATE_ON
