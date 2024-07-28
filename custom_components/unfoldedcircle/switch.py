"""Platform for Switch integration."""

from collections.abc import Callable
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform, service
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyUnfoldedCircleRemote.const import RemoteUpdateType

from .const import (
    CONF_ACTIVITIES_AS_SWITCHES,
    DOMAIN,
    UNFOLDED_CIRCLE_COORDINATOR,
    UPDATE_ACTIVITY_SERVICE,
)
from .coordinator import UnfoldedCircleRemoteCoordinator
from .entity import UnfoldedCircleEntity


@dataclass
class UnfoldedCircleSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Unfolded Circle Remote switch entities."""

    unique_id: str = ""
    control_fn: Callable = None


async def update_remote_display_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote display settings"""
    await coordinator.api.patch_remote_display_settings(enable)


async def update_remote_button_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote button settings"""
    await coordinator.api.patch_remote_button_settings(enable)


async def update_remote_sound_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote sound settings"""
    await coordinator.api.patch_remote_sound_settings(enable)


async def update_remote_haptic_settings(
    coordinator: UnfoldedCircleRemoteCoordinator, enable: bool
) -> None:
    """Update remote haptic settings"""
    await coordinator.api.patch_remote_haptic_settings(enable)


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

ATTR_PREVENT_SLEEP = "prevent_sleep"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Switch platform."""
    # Setup connection with devices
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    platform = entity_platform.async_get_current_platform()

    activities = []
    # Skip populating the array of activities in groups if the user requested that all
    # activities are created as switches
    # IF it is true, the activities array will be empty and all activities will be
    # added as switches (since non are in activity groups)
    if config_entry.options.get(CONF_ACTIVITIES_AS_SWITCHES, False) is False:
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

    @service.verify_domain_control(hass, DOMAIN)
    async def async_service_handle(service_call: ServiceCall) -> None:
        """Handle dispatched services."""

        assert platform is not None
        entities = await platform.async_extract_from_service(service_call)

        if not entities:
            return

        for entity in entities:
            assert isinstance(entity, UCRemoteSwitch)

        if service_call.service == UPDATE_ACTIVITY_SERVICE:
            coordinator = hass.data[DOMAIN][config_entry.entry_id][
                UNFOLDED_CIRCLE_COORDINATOR
            ]
            await coordinator.api.get_activity_by_id(entity.unique_id).edit(
                service_call.data
            )
            test = 1 + 1

    prevent_sleep_schema = cv.make_entity_service_schema(
        {vol.Optional(ATTR_PREVENT_SLEEP, default=False): cv.boolean}
    )

    hass.services.async_register(
        DOMAIN, UPDATE_ACTIVITY_SERVICE, async_service_handle, prevent_sleep_schema
    )


class UCRemoteSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle activity."""

    def __init__(self, coordinator, switch) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.switch = switch
        self._attr_has_entity_name = True
        self._attr_name = f"{switch.name}"
        self._attr_unique_id = switch._id
        self._state = switch.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        self.coordinator.subscribe_events["entity_activity"] = True
        self.coordinator.subscribe_events["activity_groups"] = True

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
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
        except (KeyError, IndexError):
            return
        self._state = self.switch.state
        self.async_write_ha_state()


class UCRemoteConfigSwitch(UnfoldedCircleEntity, SwitchEntity):
    """Class representing an unfolded circle setting."""

    entity_description = UNFOLDED_CIRCLE_SWITCH

    def __init__(
        self, coordinator, description: UnfoldedCircleSwitchEntityDescription
    ) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self._description = description
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_{description.unique_id}"
        self._attr_has_entity_name = True
        self._attr_name = f"{description.name}"
        key = "_" + self._description.key
        self._attr_native_value = coordinator.data.get(key)
        if coordinator.data.get(key) is True:
            self._state = "ON"
        else:
            self._state = "OFF"

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state == "ON"

    @property
    def should_poll(self) -> bool:
        return True

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
        key = "_" + self._description.key
        state = self.coordinator.data.get(key)
        if state is True:
            self._state = "ON"
        else:
            self._state = "OFF"
        self._attr_native_value = state
        self.async_write_ha_state()
