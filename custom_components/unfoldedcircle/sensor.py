"""Platform for sensor integration."""
from dataclasses import dataclass
import logging
from typing import cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import LIGHT_LUX, PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnfoldedCircleSensorEntityDescription(SensorEntityDescription):
    """Class describing Unfolded Circle Remote sensor entities."""

    unique_id: str = ""


UNFOLDED_CIRCLE_SENSOR: tuple[UnfoldedCircleSensorEntityDescription, ...] = (
    UnfoldedCircleSensorEntityDescription(
        key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
        name="Battery",
        has_entity_name=False,
        unique_id="battery",
    ),
    UnfoldedCircleSensorEntityDescription(
        key="ambient_light_intensity",
        unit_of_measurement=LIGHT_LUX,
        device_class=SensorDeviceClass.ILLUMINANCE,
        icon="mdi:sun-wireless",
        name="Illuminance",
        has_entity_name=False,
        unique_id="illuminance",
    ),
    UnfoldedCircleSensorEntityDescription(
        key="memory_available",
        unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=UnitOfInformation.MEBIBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Memory Available",
        has_entity_name=False,
        unique_id="memory_available",
        suggested_display_precision=0,
    ),
    UnfoldedCircleSensorEntityDescription(
        key="storage_available",
        unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=UnitOfInformation.MEBIBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Storage Available",
        has_entity_name=False,
        unique_id="storage_available",
        suggested_display_precision=0,
    ),
    UnfoldedCircleSensorEntityDescription(
        key="cpu_load_one",
        unit_of_measurement="load",
        entity_category=EntityCategory.DIAGNOSTIC,
        name="CPU Load Avg (1 min)",
        has_entity_name=False,
        unique_id="cpu_load_1_min",
        suggested_display_precision=2,
    ),
)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    # Verify that passed in configuration works
    if not await coordinator.api.can_connect():
        _LOGGER.error("Could not connect to remote api")
        return

    # Get Basic Device Information
    await coordinator.api.update()
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        UnfoldedCircleSensor(coordinator, description)
        for description in UNFOLDED_CIRCLE_SENSOR
    )


class UnfoldedCircleSensor(
    CoordinatorEntity[UnfoldedCircleRemoteCoordinator], SensorEntity
):
    """Unfolded Circle Sensor Class."""

    entity_description: UNFOLDED_CIRCLE_SENSOR

    def __init__(
        self, coordinator, description: UnfoldedCircleSensorEntityDescription
    ) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(self, coordinator)
        self.coordinator = coordinator

        self._attr_unique_id = (
            f"{self.coordinator.api.serial_number}_{description.unique_id}"
        )
        self._attr_name = f"{self.coordinator.api.name} {description.name}"
        self._attr_unit_of_measurement = description.unit_of_measurement
        self._attr_native_unit_of_measurement = description.unit_of_measurement
        self._device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self._attr_has_entity_name = description.has_entity_name
        self.entity_description = description
        self._state: StateType = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.coordinator.api.serial_number)
            },
            name=self.coordinator.api.name,
            manufacturer=self.coordinator.api.manufacturer,
            model=self.coordinator.api.model_name,
            sw_version=self.coordinator.api.sw_version,
            hw_version=self.coordinator.api.hw_revision,
            configuration_url=self.coordinator.api.configuration_url,
        )

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return if available."""
        return self.coordinator.api.online

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        self._attr_native_value = self.coordinator.data.get(self.entity_description.key)
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        """Return native value for entity."""
        if self.coordinator.data:
            key = "_" + self.entity_description.key
            state = self.coordinator.data.get(key)
            self._state = cast(StateType, state)
        return self._state
