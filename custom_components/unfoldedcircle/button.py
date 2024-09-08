"""Button for Unfolded Circle."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from . import UnfoldedCircleConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entity in HA."""
    coordinator = config_entry.runtime_data.coordinator
    dock_coordinators = config_entry.runtime_data.dock_coordinators
    async_add_entities([
        RebootButton(coordinator),
        UpdateCheckButton(coordinator),
    ])
    for dock_coordinator in dock_coordinators:
        async_add_entities([
            RebootDockButton(dock_coordinator),
            IdentifyDockButton(dock_coordinator),
        ])


class RebootButton(UnfoldedCircleEntity, ButtonEntity):
    """Representation of a Button entity."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_unique_id = (
            f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_restart_button"
        )
        self._attr_name = "Restart"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:gesture-tap-button"
        self._attr_device_class = ButtonDeviceClass.RESTART

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.api.online

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.post_system_command("REBOOT")


class UpdateCheckButton(UnfoldedCircleEntity, ButtonEntity):
    """Representation of a Button entity."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_update_check_button"
        self._attr_name = "Check for Update"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:gesture-tap-button"
        self._attr_device_class = ButtonDeviceClass.UPDATE

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.api.online

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.get_remote_force_update_information()
        self.async_write_ha_state()


class RebootDockButton(UnfoldedCircleDockEntity, ButtonEntity):
    """Representation of a Button entity."""

    def __init__(self, coordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_restart_button"
        self._attr_name = "Restart"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:gesture-tap-button"
        self._attr_device_class = ButtonDeviceClass.RESTART
        self._attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.send_command("REBOOT")


class IdentifyDockButton(UnfoldedCircleDockEntity, ButtonEntity):
    """Representation of a Button entity."""

    def __init__(self, coordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_identify_button"
        self._attr_name = "Identify"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:gesture-tap-button"
        self._attr_device_class = ButtonDeviceClass.IDENTIFY
        self._attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.send_command("IDENTIFY")
