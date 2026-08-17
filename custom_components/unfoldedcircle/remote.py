"""Remote sensor platform for Unfolded Circle."""

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any

from unfurled.helpers.models import UpdateType

from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UnfoldedCircleConfigEntry
from .const import COMMAND_LIST, REMOTE_ON_BEHAVIOR
from .entity import UnfoldedCircleDockEntity, UnfoldedCircleEntity
from .helpers import Command


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote sensor platform."""
    coordinator = config_entry.runtime_data.coordinator
    async_add_entities([RemoteSensor(coordinator, config_entry)])

    for (
        subentry_id,
        dock_coordinator,
    ) in config_entry.runtime_data.docks.items():
        async_add_entities(
            [
                RemoteDockSensor(
                    dock_coordinator, config_entry, config_entry.subentries[subentry_id]
                )
            ],
            config_subentry_id=subentry_id,
        )


_ACTIVITY_TRANSITION_GRACE_SECS = 0.35


class RemoteSensor(UnfoldedCircleEntity, RemoteEntity):
    """Remote Sensor."""

    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = RemoteEntityFeature.ACTIVITY

    def __init__(
        self,
        coordinator,
        config_entry: UnfoldedCircleConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_remote"
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"
        self.config_entry = config_entry
        self._pending_off_handle: asyncio.TimerHandle | None = None

        if hasattr(self.coordinator.api, "activities"):
            for activity in self.coordinator.api.activities:
                self._attr_activity_list.append(activity.name)

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    def update_state(self) -> bool:
        """Update current activity and extra state attributes"""
        self._attr_is_on = False
        self._attr_current_activity = None
        if hasattr(self.coordinator.api, "activities"):
            for activity in self.coordinator.api.activities:
                self._extra_state_attributes[activity.name] = activity.state
                if activity.is_on:
                    self._attr_current_activity = activity.name
                    self._attr_is_on = True
            for activity in self.coordinator.api.activities:
                for entity in activity.media_player_entities:
                    self._extra_state_attributes[entity.name] = entity.state

        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on, optionally starting a requested activity."""
        requested_activity = kwargs.get(ATTR_ACTIVITY)
        toggle_activity = requested_activity or self.config_entry.options.get(
            REMOTE_ON_BEHAVIOR
        )

        if toggle_activity and toggle_activity != "No Action":
            for activity in self.coordinator.api.activities:
                if activity.name == toggle_activity or activity.id == toggle_activity:
                    # Activity.turn_on() wakes the remote first when WoL is enabled.
                    await activity.turn_on()
                    self._attr_current_activity = activity.name
                    break
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        if hasattr(self.coordinator.api, "activities"):
            for activity in self.coordinator.api.activities:
                if activity.is_on:
                    await activity.turn_off()
        self._attr_is_on = False
        self.coordinator.async_set_updated_data({"updated": True})

    async def async_send_command(self, command: Iterable[str], **kwargs):
        """Send a remote command."""
        data = {}
        data["command"] = command
        data["num_repeats"] = kwargs.get("num_repeats")
        data["delay_secs"] = kwargs.get("delay_secs")
        data["hold"] = kwargs.get("hold")

        for indv_command in command:
            if indv_command in COMMAND_LIST:
                remote_command = Command(self.coordinator, self.hass, data=data)
                await remote_command.async_send()
            else:
                await self.coordinator.api.ir.send(
                    indv_command,
                    device=kwargs.get("device", ""),
                    repeat=kwargs.get("num_repeats", 0),
                )

    @callback
    def _cancel_pending_off(self) -> None:
        """Cancel a deferred off-state update during an activity handoff."""
        if self._pending_off_handle is not None:
            self._pending_off_handle.cancel()
            self._pending_off_handle = None

    @callback
    def _confirm_activity_off(self) -> None:
        """Publish off only if the activity handoff did not complete."""
        self._pending_off_handle = None
        if not self.update_state():
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any deferred state update when the entity is removed."""
        self._cancel_pending_off()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.update_state():
            self._cancel_pending_off()
            self.async_write_ha_state()
            return

        if self.coordinator.api.last_update_type == UpdateType.ACTIVITY:
            if self._pending_off_handle is None:
                self._pending_off_handle = self.hass.loop.call_later(
                    _ACTIVITY_TRANSITION_GRACE_SECS, self._confirm_activity_off
                )
            return

        if self._pending_off_handle is not None:
            return

        self.async_write_ha_state()


class RemoteDockSensor(UnfoldedCircleDockEntity, RemoteEntity):
    """Dock Remote Sensor"""

    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = (
        RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
    )

    def __init__(
        self,
        coordinator,
        config_entry: UnfoldedCircleConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, subentry)
        self._attr_unique_id = f"{subentry.unique_id}_{self.coordinator.api.device.model_number}_{self.coordinator.api.device.serial_number}_remote"
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = None
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"
        self._attr_dock_name = subentry.title

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    def update_state(self) -> bool:
        """Update current activity and extra state attributes"""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False

    async def async_send_command(self, command: Iterable[str], **kwargs):
        """Send a remote command."""
        for indv_command in command:
            await self.coordinator.api.ir.send(
                indv_command,
                device=kwargs.get("device", ""),
                repeat=kwargs.get("num_repeats", 0),
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state()
        self.async_write_ha_state()
