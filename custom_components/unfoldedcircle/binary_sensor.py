"""Binary sensor platform for Unfolded Circle."""

from typing import Any, Mapping

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import ATTR_BATTERY_CHARGING, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import UnfoldedCircleEntity
from . import UnfoldedCircleConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""

    coordinator = config_entry.runtime_data.coordinator
    async_add_entities(
        [
            BatteryBinarySensor(coordinator),
            PollingBinarySensor(coordinator),
        ]
    )


class PollingBinarySensor(UnfoldedCircleEntity, BinarySensorEntity):
    """Sensor indicating if HTTP Polling is active"""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    def __init__(self, coordinator) -> None:
        """Initialize Binary Sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_polling_status"
        self._attr_name = "Polling Status"
        self._attr_native_value = self.coordinator.polling_data
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:swap-horizontal"
        self._attr_entity_registry_enabled_default = False
        self._attr_entity_registry_visible_default = False
        self._attr_extra_state_attributes = {}

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        self._attr_native_value = self.coordinator.polling_data
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.coordinator.polling_data
        self._attr_extra_state_attributes["Polling state"] = (
            self.coordinator.polling_data
        )
        self._attr_extra_state_attributes["Websocket state"] = (
            self.coordinator.websocket_task is not None
        )
        self._attr_extra_state_attributes["Websocket events"] = ", ".join(
            self.coordinator.websocket.events_to_subscribe
        )
        self.async_write_ha_state()


class BatteryBinarySensor(UnfoldedCircleEntity, BinarySensorEntity):
    """Class representing a binary sensor."""

    device_class = ATTR_BATTERY_CHARGING

    async def async_added_to_hass(self) -> None:
        self.coordinator.subscribe_events["battery_status"] = True
        await super().async_added_to_hass()

    def __init__(self, coordinator) -> None:
        """Initialize Binary Sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_charging_status"
        self._attr_translation_key = "charging_status"
        self._attr_name = "Charging Status"
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
