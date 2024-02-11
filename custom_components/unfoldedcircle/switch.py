"""Platform for Switch integration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
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
class UnfoldedCircleSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Unfolded Circle Remote switch entities."""

    unique_id: str = ""
    control_fn: Callable = None
    # toggle_fn: Callable[[SwitchEntity, bool], tuple[Callable[..., True], dict]]


def update_remote_display_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    coordinator.api.patch_remote_display_settings(enable)


def update_remote_button_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    coordinator.api.patch_remote_button_settings(enable)


def update_remote_sound_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    coordinator.api.patch_remote_sound_settings(enable)


def update_remote_haptic_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    coordinator.api.patch_remote_haptic_settings(enable)


UNFOLDED_CIRCLE_SWITCH: tuple[UnfoldedCircleSwitchEntityDescription, ...] = (
    UnfoldedCircleSwitchEntityDescription(
        key="display_auto_brightness",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Display Auto Brightness",
        unique_id="display_auto_brightness",
        icon="mdi:brightness-auto",
        control_fn=update_remote_display_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="button_backlight",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Button Backlight",
        unique_id="button_backlight",
        icon="mdi:keyboard-settings",
        control_fn=update_remote_button_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="sound_effects",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Sound Effects",
        unique_id="sound_effects",
        icon="mdi:music",
        control_fn=update_remote_sound_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="haptic_feedback",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Haptic Feedback",
        unique_id="haptic_feedback",
        icon="mdi:vibrate",
        control_fn=update_remote_haptic_settings,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Switch platform."""
    # Setup connection with devices
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    # Verify that passed in configuration works
    if not await coordinator.api.can_connect():
        _LOGGER.error("Could not connect to Remote")
        return

    # Get Basic Device Information
    await coordinator.api.update()

    await coordinator.async_config_entry_first_refresh()

    # Add devices
    await coordinator.api.get_activities()
    async_add_entities(
        UCRemoteSwitch(coordinator, switch) for switch in coordinator.api.activities
    )

    async_add_entities(
        UCRemoteConfigSwitch(coordinator, configSwitch)
        for configSwitch in UNFOLDED_CIRCLE_SWITCH
    )


class UCRemoteSwitch(CoordinatorEntity[UnfoldedCircleRemoteCoordinator], SwitchEntity):
    """Class representing an unfolded circle activity."""

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

    def __init__(self, coordinator, switch) -> None:
        """Initialize a switch."""
        super().__init__(self, coordinator)
        self.coordinator = coordinator
        self.switch = switch
        self._name = f"{self.coordinator.api.name} {switch.name}"
        self._attr_name = f"{self.coordinator.api.name} {switch.name}"
        self._attr_unique_id = switch._id
        self._state = switch.state
        self._attr_icon = "mdi:remote-tv"
        self._state: StateType = None

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state in ("ON", "RUNNING")

    async def async_turn_on(self, **kwargs) -> None:
        """Instruct the switch to turn on."""
        await self.switch.turn_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Instruct the switch to turn off."""
        await self.switch.turn_off()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = self.switch.state
        self.async_write_ha_state()


class UCRemoteConfigSwitch(
    CoordinatorEntity[UnfoldedCircleRemoteCoordinator], SwitchEntity
):
    """Class representing an unfolded circle activity."""

    entity_description = UNFOLDED_CIRCLE_SWITCH

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
        self, coordinator, description: UnfoldedCircleSwitchEntityDescription
    ) -> None:
        """Initialize a switch."""
        super().__init__(self, coordinator)
        self._description = description
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = (
            f"{self.coordinator.api.serial_number}_{description.unique_id}"
        )
        self._attr_name = f"{self.coordinator.api.name} {description.name}"
        key = "_" + self._description.key
        self._state = coordinator.data.get(key)

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state is True

    async def async_turn_on(self, **kwargs) -> None:
        """Instruct the switch to turn on."""
        self.entity_description.control_fn(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Instruct the switch to turn off."""
        self.entity_description.control_fn(False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = "_" + self._description.key
        state = self.coordinator.data.get(key)
        self._state = cast(StateType, state)
        self.async_write_ha_state()
