"""Base entity for Unfolded Circle Remote Integration"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import UnfoldedCircleRemoteCoordinator
from .const import DOMAIN
from .coordinator import UnfoldedCircleDockCoordinator
from . import UnfoldedCircleConfigEntry


async def async_setup_entry(hass: HomeAssistant, config_entry: UnfoldedCircleConfigEntry):
    """Add sensors for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator


class UnfoldedCircleEntity(CoordinatorEntity[UnfoldedCircleRemoteCoordinator]):
    """Common entity class for all Unfolded Circle entities"""

    def __init__(self, coordinator) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self.coordinator: UnfoldedCircleRemoteCoordinator = coordinator
        self.coordinator.entities.append(self)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
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

    @property
    def should_poll(self) -> bool:
        """Should the entity poll for updates?"""
        return False


class UnfoldedCircleDockEntity(CoordinatorEntity[UnfoldedCircleDockCoordinator]):
    """Common entity class for all Unfolded Circle Dock entities"""

    def __init__(self, coordinator) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.coordinator.entities.append(self)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
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
            sw_version=self.coordinator.api.software_version,
            hw_version=self.coordinator.api.hardware_revision,
            configuration_url=self.coordinator.api.remote_configuration_url,
        )

    @property
    def should_poll(self) -> bool:
        """Should the entity poll for updates?"""
        return True
