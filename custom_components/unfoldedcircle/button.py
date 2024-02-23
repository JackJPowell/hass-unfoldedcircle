"""Button for Unfolded Circle."""
import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNFOLDED_CIRCLE_API, UNFOLDED_CIRCLE_COORDINATOR
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entity in HA."""
    remote = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_API]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    new_devices = []
    new_devices.append(Button(coordinator, remote))
    if new_devices:
        async_add_entities(new_devices)


class Button(UnfoldedCircleEntity, ButtonEntity):
    """Representation of a Button entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator, remote) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._remote = remote
        self._attr_unique_id = f"{self._remote.serial_number}_restart_button"
        self._attr_name = f"{self._remote.name} Restart Remote"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._remote.online

    async def async_press(self) -> None:
        """Press the button."""
        await self._remote.post_system_command("REBOOT")
