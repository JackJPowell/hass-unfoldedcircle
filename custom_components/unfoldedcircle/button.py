"""Button for Unfolded Circle."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .entity import UnfoldedCircleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entity in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    async_add_entities([RebootButton(coordinator), UpdateCheckButton(coordinator)])


class RebootButton(UnfoldedCircleEntity, ButtonEntity):
    """Representation of a Button entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.serial_number}_restart_button"
        self._attr_name = f"{self.coordinator.api.name} Restart Remote"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.api.online

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.post_system_command("REBOOT")


class UpdateCheckButton(UnfoldedCircleEntity, ButtonEntity):
    """Representation of a Button entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{self.coordinator.api.serial_number}_update_check_button"
        )
        self._attr_name = f"{self.coordinator.api.name} Check for Update"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.api.online

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api.get_remote_force_update_information()
        self.async_write_ha_state()
