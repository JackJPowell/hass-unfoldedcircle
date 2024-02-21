"""Binary sensor platform for Unfolded Circle."""
import logging
from typing import Mapping, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_BATTERY_CHARGING, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    new_devices = []
    new_devices.append(BatteryBinarySensor(coordinator))
    new_devices.append(PollingBinarySensor(coordinator))
    if new_devices:
        async_add_entities(new_devices)


class PollingBinarySensor(
    UnfoldedCircleEntity, BinarySensorEntity
):
    """Class representing a binary sensor."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    def __init__(self, coordinator) -> None:
        """Initialize Binary Sensor."""
        super().__init__(coordinator)

        # As per the sensor, this must be a unique value within this domain.
        self._attr_unique_id = f"{self.coordinator.api.serial_number}_polling_status"

        # The name of the entity
        self._attr_name = f"{self.coordinator.api.name} Polling Status"
        self._attr_native_value = self.coordinator.polling_data
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._extra_state_attributes = {}

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        self._attr_native_value = self.coordinator.polling_data
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.coordinator.polling_data
        self._extra_state_attributes["Polling state"] = self.coordinator.polling_data
        self._extra_state_attributes["Websocket state"] = self.coordinator.websocket_task is not None
        self._extra_state_attributes["Websocket events"] = (
            ", ".join(self.coordinator.remote_websocket.events_to_subscribe))
        self.async_write_ha_state()

class BatteryBinarySensor(
    UnfoldedCircleEntity, BinarySensorEntity
):
    """Class representing a binary sensor."""

    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = ATTR_BATTERY_CHARGING

    async def async_added_to_hass(self) -> None:
        self.coordinator.subscribe_events["battery_status"] = True
        await super().async_added_to_hass()

    def __init__(self, coordinator) -> None:
        """Initialize Binary Sensor."""
        super().__init__(coordinator)

        # As per the sensor, this must be a unique value within this domain.
        self._attr_unique_id = f"{self.coordinator.api.serial_number}_charging_status"

        # The name of the entity
        self._attr_name = f"{self.coordinator.api.name} Charging Status"
        self._attr_native_value = False

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        self._attr_native_value = self.coordinator.api.is_charging
        return self._attr_native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.coordinator.api.is_charging
        self.async_write_ha_state()
