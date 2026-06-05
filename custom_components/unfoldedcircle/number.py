"""Platform for Number integration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
)

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigSubentry
from .coordinator import (
    UnfoldedCircleRemoteCoordinator,
    UnfoldedCircleDockCoordinator,
)
from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from . import UnfoldedCircleConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnfoldedCircleNumberEntityDescription(NumberEntityDescription):
    """Class describing Unfolded Circle Remote number entities."""

    unique_id: str = ""
    control_fn: Callable = None


async def update_remote_display_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    await coordinator.api.settings.update_display(brightness=value)


async def update_remote_sound_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    await coordinator.api.settings.update_sound(volume=value)


async def update_remote_display_timeout_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    await coordinator.api.settings.update_power_saving(display_timeout=value)


async def update_remote_wakeup_sensitivity_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    await coordinator.api.settings.update_power_saving(wakeup_sensitivity=value)


async def update_remote_sleep_timeout_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, value: int
) -> None:
    await coordinator.api.settings.update_power_saving(sleep_timeout=value)


UNFOLDED_CIRCLE_NUMBER: tuple[UnfoldedCircleNumberEntityDescription, ...] = (
    UnfoldedCircleNumberEntityDescription(
        key="display_brightness",
        translation_key="display_brightness",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Display Brightness",
        unique_id="display_brightness",
        control_fn=update_remote_display_settings,
        native_min_value=0,
        native_max_value=100,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="sound_effects_volume",
        translation_key="sound_effects_volume",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Sound Effects Volume",
        unique_id="sound_effects_volume",
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
        control_fn=update_remote_display_timeout_settings,
        native_min_value=0,
        native_max_value=60,
    ),
    UnfoldedCircleNumberEntityDescription(
        key="wakeup_sensitivity",
        translation_key="wakeup_sensitivity",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="Wake Sensitivity",
        unique_id="wakeup_sensitivity",
        control_fn=update_remote_wakeup_sensitivity_settings,
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
        control_fn=update_remote_sleep_timeout_settings,
        native_min_value=0,
        native_max_value=1800,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Number platform."""
    # Setup connection with devices
    coordinator = config_entry.runtime_data.coordinator
    async_add_entities(
        UCRemoteNumber(coordinator, Number) for Number in UNFOLDED_CIRCLE_NUMBER
    )

    for (
        subentry_id,
        dock_coordinator,
    ) in config_entry.runtime_data.docks.items():
        async_add_entities(
            [
                UCDockNumber(
                    dock_coordinator,
                    description,
                    config_entry,
                    config_entry.subentries[subentry_id],
                )
                for description in UNFOLDED_CIRCLE_DOCK_NUMBER
            ],
            config_subentry_id=subentry_id,
        )


class UCRemoteNumber(UnfoldedCircleEntity, NumberEntity):
    """Class representing an unfolded circle number."""

    entity_description = UNFOLDED_CIRCLE_NUMBER

    def __init__(
        self, coordinator, description: UnfoldedCircleNumberEntityDescription
    ) -> None:
        """Initialize a Number."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_{description.unique_id}"
        self._attr_native_value = self._get_value()

    def _get_value(self):
        """Return the current value from the coordinator API."""
        key = self.entity_description.key
        if key == "display_brightness":
            return self.coordinator.api.settings.display.brightness
        if key == "sound_effects_volume":
            return self.coordinator.api.settings.sound.volume
        if key == "display_timeout":
            return self.coordinator.api.settings.power_saving.display_off_sec
        if key == "wakeup_sensitivity":
            return self.coordinator.api.settings.power_saving.wakeup_sensitivity
        if key == "sleep_timeout":
            return self.coordinator.api.settings.power_saving.standby_sec
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        value_int = int(value)
        await self.entity_description.control_fn(self.coordinator, value_int)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._get_value()
        self.async_write_ha_state()


async def update_dock_led_brightness(
    coordinator: UnfoldedCircleDockCoordinator, value: int
) -> None:
    await coordinator.api.system.set_led_brightness(value)


UNFOLDED_CIRCLE_DOCK_NUMBER: tuple[UnfoldedCircleNumberEntityDescription, ...] = (
    UnfoldedCircleNumberEntityDescription(
        key="led_brightness",
        translation_key="led_brightness",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        name="LED Brightness",
        unique_id="display_brightness",
        control_fn=update_dock_led_brightness,
        native_min_value=0,
        native_max_value=100,
    ),
)


class UCDockNumber(UnfoldedCircleDockEntity, NumberEntity):
    """Class representing an unfolded circle number."""

    entity_description = UNFOLDED_CIRCLE_NUMBER

    def __init__(
        self,
        coordinator,
        description: UnfoldedCircleNumberEntityDescription,
        config_entry: UnfoldedCircleConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize a Number."""
        super().__init__(coordinator, config_entry, subentry)
        self.entity_description = description
        self._attr_unique_id = f"{subentry.unique_id}_{self.coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_{description.unique_id}"
        self._attr_native_value = self.coordinator.api.state.led_brightness

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        value_int = int(value)
        await self.entity_description.control_fn(self.coordinator, value_int)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.coordinator.api.state.led_brightness
        self.async_write_ha_state()
