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
from homeassistant.helpers.typing import StateType

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator
from .entity import UnfoldedCircleEntity
from .pyUnfoldedCircleRemote.const import RemoteUpdateType

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnfoldedCircleSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Unfolded Circle Remote switch entities."""

    unique_id: str = ""
    control_fn: Callable = None


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
) -> None:
    """Set up the Switch platform."""
    # Setup connection with devices
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    activities = []
    for activity_group in coordinator.api.activity_groups:
        activities.extend(activity_group.activities)

    # Create switch for each activity only for activities not defined in any activity group
    async_add_entities(
        UCRemoteSwitch(coordinator, switch)
        for switch in filter(lambda a: a not in activities, coordinator.api.activities)
    )

    async_add_entities(
        UCRemoteConfigSwitch(coordinator, configSwitch)
        for configSwitch in UNFOLDED_CIRCLE_SWITCH
    )


class UCRemoteSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle activity."""

    def __init__(self, coordinator, switch) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.switch = switch
        self._attr_name = f"{self.coordinator.api.name} {switch.name}"
        # self._attr_unique_id = switch._id
        self._state = switch.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        self.coordinator.subscribe_events["entity_activity"] = True
        self.coordinator.subscribe_events["activity_groups"] = True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        self.coordinator.subscribe_events["entity_activity"] = True
        self.coordinator.subscribe_events["activity_groups"] = True

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
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
        except (KeyError, IndexError):
            return
        self._state = self.switch.state
        self.async_write_ha_state()


class UCRemoteConfigSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle activity."""

    entity_description = UNFOLDED_CIRCLE_SWITCH

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
