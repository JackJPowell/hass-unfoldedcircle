"""Platform for Number integration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType, StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnfoldedCircleNumberEntityDescription(NumberEntityDescription):
    """Class describing Unfolded Circle Remote number entities."""

    unique_id: str = ""
    control_fn: Callable = None
    # toggle_fn: Callable[[SwitchEntity, bool], tuple[Callable[..., True], dict]]


def update_remote_display_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    coordinator.api.patch_remote_display_settings(value)


def update_remote_button_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    coordinator.api.patch_remote_button_settings(value)


def update_remote_sound_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    coordinator.api.patch_remote_sound_settings(value)


def update_remote_power_saving_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    coordinator.api.patch_remote_power_saving_settings(value)


UNFOLDED_CIRCLE_NUMBER: tuple[UnfoldedCircleNumberEntityDescription, ...] = (
    UnfoldedCircleNumberEntityDescription(
        key="display_brightness",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Display Brightness",
        unique_id="display_brightness",
        icon="mdi:brightness-5",
        control_fn=update_remote_display_settings,
        native_min_value=0,
        native_max_value=100,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="button_backlight_brightness",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Button Backlight Brightness",
        unique_id="button_backlight_brightness",
        icon="mdi:keyboard-settings-outline",
        control_fn=update_remote_button_settings,
        native_min_value=0,
        native_max_value=100,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="sound_effects_volume",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Sound Effects Volume",
        unique_id="sound_effects_volume",
        icon="mdi:volume-medium",
        control_fn=update_remote_sound_settings,
        native_min_value=0,
        native_max_value=100,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="display_timeout",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Display Timeout",
        unique_id="display_timeout",
        icon="mdi:vibrate",
        control_fn=update_remote_power_saving_settings,
        native_min_value=0,
        native_max_value=60,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="wakeup_sensitivity",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Wake Sensitivity",
        unique_id="wakeup_sensitivity",
        icon="mdi:sleep-off",
        control_fn=update_remote_power_saving_settings,
        native_min_value=0,
        native_max_value=3,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="sleep_timeout",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Sleep Timeout",
        unique_id="sleep_timeout",
        icon="mdi:power-sleep",
        control_fn=update_remote_power_saving_settings,
        native_min_value=0,
        native_max_value=1800,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Number platform."""
    # Setup connection with devices
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    # Verify that passed in configuration works
    if not await coordinator.api.can_connect():
        _LOGGER.error("Could not connect to Remote")
        return

    # Get Basic Device Information
    await coordinator.api.update()

    await coordinator.async_config_entry_first_refresh()
    async_add_entities(
        UCRemoteNumber(coordinator, Number) for Number in UNFOLDED_CIRCLE_NUMBER
    )


class UCRemoteNumber(CoordinatorEntity[UnfoldedCircleRemoteCoordinator], NumberEntity):
    """Class representing an unfolded circle number."""

    entity_description = UNFOLDED_CIRCLE_NUMBER

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

    def __init__(
        self, coordinator, description: UnfoldedCircleNumberEntityDescription
    ) -> None:
        """Initialize a Number."""
        super().__init__(self, coordinator)
        self._description = description
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = (
            f"{self.coordinator.api.serial_number}_{description.unique_id}"
        )
        self._attr_name = f"{self.coordinator.api.name} {description.name}"
        key = "_" + description.key
        self._attr_native_value = coordinator.data.get(key)
        self._attr_icon = description.icon
        self._attr_entity_category = description.entity_category
        self._attr_device_class = description.device_class
        self._attr_min_value = description.min_value
        self._attr_max_value = description.max_value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        # control_fn=update_remote_haptic_settings,

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = "_" + self._description.key
        state = self.coordinator.data.get(key)
        self._attr_native_value = cast(StateType, state)
        self.async_write_ha_state()
