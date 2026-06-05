"""Platform for Switch integration."""

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from unfurled.helpers.models import UpdateType

from .const import CONF_ACTIVITIES_AS_SWITCHES
from .coordinator import UnfoldedCircleRemoteCoordinator
from .entity import UnfoldedCircleEntity
from . import UnfoldedCircleConfigEntry


@dataclass(frozen=True)
class UnfoldedCircleSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Unfolded Circle Remote switch entities."""

    unique_id: str = ""
    control_fn: Callable = None


async def update_remote_display_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote display settings"""
    await coordinator.api.settings.update_display(auto_brightness=enable)


async def update_remote_sound_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote sound settings"""
    await coordinator.api.settings.update_sound(enabled=enable)


async def update_remote_haptic_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote haptic settings"""
    await coordinator.api.settings.update_haptic(enabled=enable)


async def update_remote_network_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote network settings"""
    await coordinator.api.settings.update_network(wake_on_wlan=enable)


async def update_remote_wireless_charging_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote wireless charging settings"""
    await coordinator.api.system.set_wireless_charging(enabled=enable)


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
        key="sound_effects",
        translation_key="sound_effects",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Sound Effects",
        unique_id="sound_effects",
        control_fn=update_remote_sound_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="haptic_feedback",
        translation_key="haptic_feedback",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Haptic Feedback",
        unique_id="haptic_feedback",
        control_fn=update_remote_haptic_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="wake_on_lan",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Wake on Lan",
        unique_id="wake_on_lan",
        icon="mdi:lan-check",
        control_fn=update_remote_network_settings,
    ),
    UnfoldedCircleSwitchEntityDescription(
        key="is_wireless_charging_enabled",
        translation_key="is_wireless_charging_enabled",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        name="Wireless Charging",
        unique_id="is_wireless_charging_enabled",
        control_fn=update_remote_wireless_charging_settings,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Switch platform."""
    coordinator = config_entry.runtime_data.coordinator

    activities = []
    if config_entry.options.get(CONF_ACTIVITIES_AS_SWITCHES, False) is False:
        for activity_group in coordinator.api.activity_groups:
            activities.extend(activity_group.activities)

    async_add_entities(
        UCRemoteSwitch(coordinator, switch)
        for switch in filter(lambda a: a not in activities, coordinator.api.activities)
    )

    # Remove switches that are not supported by the remote
    switches = UNFOLDED_CIRCLE_SWITCH
    if not coordinator.api.wake_on_lan_available:
        switches = tuple(
            filter(lambda s: s.key != "wake_on_lan", UNFOLDED_CIRCLE_SWITCH)
        )
    if "WIRELESS_CHARGING" not in coordinator.api.system.flags.charging_options:
        switches = tuple(
            filter(lambda s: s.key != "is_wireless_charging_enabled", switches)
        )

    async_add_entities(
        UCRemoteConfigSwitch(coordinator, configSwitch) for configSwitch in switches
    )


class UCRemoteSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle activity."""

    def __init__(self, coordinator, switch) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.switch = switch
        self._attr_name = switch.name
        self._attr_unique_id = f"{coordinator.api.device.model_number}_{coordinator.api.device.serial_number}_{switch._id}"
        self._state = switch.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self.switch._state in ("ON", "RUNNING")

    async def async_turn_on(self, **kwargs) -> None:
        """Instruct the switch to turn on."""
        await self.switch.turn_on()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Instruct the switch to turn off."""
        await self.switch.turn_off()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != UpdateType.ACTIVITY:
                return
        except (KeyError, IndexError):
            return
        self._state = self.switch.state
        self.async_write_ha_state()


def _get_config_switch_value(api, key: str) -> bool:
    """Return the current boolean value for a config switch key."""
    if key == "display_auto_brightness":
        return bool(api.settings.display.auto_brightness)
    if key == "sound_effects":
        return bool(api.settings.sound.enabled)
    if key == "haptic_feedback":
        return bool(api.settings.haptic.enabled)
    if key == "wake_on_lan":
        return bool(api.settings.network.wifi.wake_on_wlan)
    if key == "is_wireless_charging_enabled":
        return bool(api.system.flags.wireless_charging_enabled)
    return False


class UCRemoteConfigSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle setting."""

    def __init__(
        self, coordinator, description: UnfoldedCircleSwitchEntityDescription
    ) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_{description.unique_id}"
        self._state = _get_config_switch_value(coordinator.api, description.key)

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        """Instruct the switch to turn on."""
        await self.entity_description.control_fn(self.coordinator, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Instruct the switch to turn off."""
        await self.entity_description.control_fn(self.coordinator, False)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = _get_config_switch_value(
            self.coordinator.api, self.entity_description.key
        )
        self.async_write_ha_state()
