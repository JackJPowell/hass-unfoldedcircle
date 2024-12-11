"""Platform for sensor integration."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import StateType

from .entity import UnfoldedCircleEntity
from . import UnfoldedCircleConfigEntry


@dataclass(frozen=True)
class UnfoldedCircleSensorEntityDescription(SensorEntityDescription):
    """Class describing Unfolded Circle Remote sensor entities."""

    unique_id: str = ""


UNFOLDED_CIRCLE_SENSOR: tuple[UnfoldedCircleSensorEntityDescription, ...] = (
    UnfoldedCircleSensorEntityDescription(
        key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
        name="Battery",
        unique_id="battery",
    ),
    UnfoldedCircleSensorEntityDescription(
        key="ambient_light_intensity",
        unit_of_measurement=LIGHT_LUX,
        device_class=SensorDeviceClass.ILLUMINANCE,
        icon="mdi:sun-wireless",
        name="Illuminance",
        unique_id="illuminance",
    ),
    UnfoldedCircleSensorEntityDescription(
        key="power_mode",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:power-plug-battery",
        name="Power Mode",
        unique_id="power_mode",
    ),
    UnfoldedCircleSensorEntityDescription(
        key="memory_available",
        unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=UnitOfInformation.MEBIBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Memory Available",
        unique_id="memory_available",
        suggested_display_precision=0,
        icon="mdi:memory",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    UnfoldedCircleSensorEntityDescription(
        key="storage_available",
        unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=UnitOfInformation.MEBIBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Storage Available",
        unique_id="storage_available",
        suggested_display_precision=0,
        icon="mdi:harddisk",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    UnfoldedCircleSensorEntityDescription(
        key="cpu_load_one",
        unit_of_measurement="load",
        entity_category=EntityCategory.DIAGNOSTIC,
        name="CPU Load Avg (1 min)",
        unique_id="cpu_load_1_min",
        suggested_display_precision=2,
        icon="mdi:cpu-64-bit",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    UnfoldedCircleSensorEntityDescription(
        key="remote_entities",
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Remote entities",
        unique_id="remote_entities",
        icon="mdi:remote",
        suggested_display_precision=0,
        entity_registry_enabled_default=True,
        entity_registry_visible_default=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: UnfoldedCircleConfigEntry, async_add_entities
):
    """Add sensors for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_entities(
        UnfoldedCircleSensor(coordinator, description)
        for description in UNFOLDED_CIRCLE_SENSOR
    )


class UnfoldedCircleSensor(UnfoldedCircleEntity, SensorEntity):
    """Unfolded Circle Sensor Class."""

    entity_description = UNFOLDED_CIRCLE_SENSOR

    def __init__(
        self,
        coordinator,
        description: UnfoldedCircleSensorEntityDescription,
    ) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_{description.unique_id}"
        self._attr_has_entity_name = True
        self._attr_name = description.name
        self._attr_unit_of_measurement = description.unit_of_measurement
        self._attr_native_unit_of_measurement = description.unit_of_measurement
        self._device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self.entity_description = description
        self._state: StateType = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Add websocket events according to corresponding entities
        if self.entity_description.key == "ambient_light_intensity":
            self.coordinator.subscribe_events["ambient_light"] = True
        if self.entity_description.key == "battery_level":
            self.coordinator.subscribe_events["battery_status"] = True
        if self.entity_description.key == "power_mode":
            self.coordinator.subscribe_events["configuration"] = True
        # Enable polling if one of those entities is enabled
        if self.entity_description.key in [
            "memory_available",
            "storage_available",
            "cpu_load_one",
        ]:
            self.coordinator.polling_data = True

        if self.entity_description.key == "remote_entities":
            self._attr_extra_state_attributes = {"Synchronized entities": 0}
            if self.coordinator.config_entry.data.get("available_entities", None):
                self._attr_extra_state_attributes["Available entities"] = (
                    self.coordinator.config_entry.data.get("available_entities", [])
                )
                self._attr_extra_state_attributes["Synchronized entities"] = len(
                    self._attr_extra_state_attributes["Available entities"]
                )

        await super().async_added_to_hass()

    def get_value(self) -> StateType:
        """return native value of entity"""
        if self.entity_description.key == "remote_entities":
            return self._attr_extra_state_attributes.get("Synchronized entities", 0)
        if self.coordinator.data:
            self._state = getattr(self.coordinator.api, self.entity_description.key)
            self._attr_native_value = self._state
        return self._state

    @property
    def available(self) -> bool:
        """Return if available."""
        return self.coordinator.api.online

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.get_value()
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        """Return native value for entity."""
        return self.get_value()
