"""Base entity for Unfolded Circle Remote Integration"""

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import UnfoldedCircleConfigEntry, UnfoldedCircleRemoteCoordinator
from .const import DOMAIN
from .coordinator import UnfoldedCircleDockCoordinator


class UnfoldedCircleEntity(CoordinatorEntity[UnfoldedCircleRemoteCoordinator]):
    """Common entity class for all Unfolded Circle entities"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
    ) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    self.coordinator.api.model_number,
                    self.coordinator.api.serial_number,
                )
            },
            name=self.coordinator.api.name,
            manufacturer=self.coordinator.api.manufacturer,
            model=self.coordinator.api.model_name,
            sw_version=self.coordinator.api.sw_version,
            hw_version=self.coordinator.api.hw_revision,
            configuration_url=self.coordinator.api.configuration_url,
        )


class UnfoldedCircleDockEntity(CoordinatorEntity[UnfoldedCircleDockCoordinator]):
    """Common entity class for all Unfolded Circle Dock entities"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        entry: UnfoldedCircleConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self.subentry = subentry
        remote_coordinator = self.entry.runtime_data.coordinator

        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    self.subentry.unique_id,
                    self.coordinator.api.model_number,
                    self.coordinator.api.serial_number,
                )
            },
            name=self.coordinator.api.name,
            manufacturer=self.coordinator.api.manufacturer,
            model=self.coordinator.api.model_name,
            sw_version=self.coordinator.api.software_version,
            hw_version=self.coordinator.api.hardware_revision,
            configuration_url=self.coordinator.api.remote_configuration_url,
            via_device=(
                DOMAIN,
                remote_coordinator.api.model_number,
                remote_coordinator.api.serial_number,
            ),
        )
