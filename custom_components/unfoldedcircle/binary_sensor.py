"""Binary sensor platform for Unfolded Circle."""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_BATTERY_CHARGING
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    new_devices.append(BinarySensor(remote))
    if new_devices:
        async_add_entities(new_devices)


class BinarySensor(BinarySensorEntity):
    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = ATTR_BATTERY_CHARGING

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
