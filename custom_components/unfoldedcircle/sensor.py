"""Platform for sensor integration."""
# This file shows the setup for the sensors associated with the cover.
# They are setup in the same way with the call to the async_setup_entry function
# via HA from the module __init__. Each sensor has a device_class, this tells HA how
# to display it in the UI (for know types). The unit_of_measurement property tells HA
# what the unit is, so it can display the correct range. For predefined types (such as
# battery), the unit_of_measurement should match what's expected.
import logging
from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_ILLUMINANCE,
    PERCENTAGE,
    DATA_MEBIBYTES,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import SensorStateClass

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# See cover.py for more details.
# Note how both entities for each roller sensor (battry and illuminance) are added at
# the same time to the same list. This way only a single async_add_devices call is
# required.
async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    remote = hass.data[DOMAIN][config_entry.entry_id]

    # Verify that passed in configuration works
    if not await remote.can_connect():
        _LOGGER.error("Could not connect to Remote")
        return

    # Get Basic Device Information
    await remote.update()

    new_devices = []
    new_devices.append(BatterySensor(remote))
    new_devices.append(IlluminanceSensor(remote))
    new_devices.append(MemorySensor(remote))
    new_devices.append(StorageSensor(remote))
    new_devices.append(LoadSensor(remote))
    if new_devices:
        async_add_entities(new_devices)


# This base class shows the common properties and methods for a sensor as used in this
# example. See each sensor for further details about properties and methods that
# have been overridden.
class SensorBase(Entity):
    should_poll = True

    def __init__(self, remote):
        """Initialize the sensor."""
        self._remote = remote

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
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

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        return self._remote.online

    # async def async_added_to_hass(self):
    #     """Run when this Entity has been added to HA."""
    #     # Sensors should also register callbacks to HA when their state changes
    #     self._remote.register_callback(self.async_write_ha_state)

    # async def async_will_remove_from_hass(self):
    #     """Entity being removed from hass."""
    #     # The opposite of async_added_to_hass. Remove any registered call backs here.
    #     self._remote.remove_callback(self.async_write_ha_state)

    async def async_update(self) -> None:
        await self._remote.update()


class BatterySensor(SensorBase):
    """Representation of a Sensor."""

    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = DEVICE_CLASS_BATTERY

    # The unit of measurement for this entity. As it's a DEVICE_CLASS_BATTERY, this
    # should be PERCENTAGE. A number of units are supported by HA, for some
    # examples, see:
    # https://developers.home-assistant.io/docs/core/entity/sensor#available-device-classes
    _attr_unit_of_measurement = PERCENTAGE

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)

        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_battery"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Battery"

    # The value of this sensor. As this is a DEVICE_CLASS_BATTERY, this value must be
    # the battery level as a percentage (between 0 and 100)
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote.battery_level


# This is another sensor, but more simple compared to the battery above. See the
# comments above for how each field works.
class IlluminanceSensor(SensorBase):
    """Representation of a Sensor."""

    device_class = DEVICE_CLASS_ILLUMINANCE
    _attr_unit_of_measurement = "lx"
    _attr_icon = "mdi:sun-wireless"

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_illuminance"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Illuminance"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote.ambient_light_intensity


class ChargingSensor(SensorBase):
    """Representation of a Sensor."""

    device_class = DEVICE_CLASS_ILLUMINANCE
    _attr_unit_of_measurement = "lx"

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_illuminance"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Illuminance"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote.ambient_light_intensity


class MemorySensor(SensorBase):
    """Representation of a Sensor."""

    device_class = DATA_MEBIBYTES
    _attr_unit_of_measurement = "MiB"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_memory_available"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Memory Available"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote.memory_available


class StorageSensor(SensorBase):
    """Representation of a Sensor."""

    device_class = DATA_MEBIBYTES
    _attr_unit_of_measurement = "MiB"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_storage_available"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Storage Available"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote.storage_available

class LoadSensor(SensorBase):
    """Representation of a Sensor."""

    _attr_unit_of_measurement = "Load"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, remote):
        """Initialize the sensor."""
        super().__init__(remote)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_cpu_load_1_min"

        # The name of the entity
        self._attr_name = f"{self._remote.name} CPU Load Avg (1 min)"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._remote._cpu_load.get("one")