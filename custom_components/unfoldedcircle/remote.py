"""Remote sensor platform for Unfolded Circle."""

from typing import Any, Mapping, Iterable

from homeassistant.components.remote import (
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import REMOTE_ON_BEHAVIOR, COMMAND_LIST
from .helpers import Command
from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from . import UnfoldedCircleConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
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
        self._attr_unique_id = f"{subentry.unique_id}_{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_remote"
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = None
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"
        self.dock_name = subentry.title

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
        return

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False

    async def async_send_command(self, command: Iterable[str], **kwargs):
        """Send a remote command."""
        for indv_command in command:
            await self.coordinator.api.send_remote_command(
                device=kwargs.get("device"),
                command=indv_command,
                repeat=kwargs.get("num_repeats"),
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state()
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self.coordinator.subscribe_events["all"] = True
        await super().async_added_to_hass()


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
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_remote"
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"
        self.config_entry = config_entry

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
                if activity.is_on():
                    self._attr_current_activity = activity.name
                    self._attr_is_on = True
            for activity in self.coordinator.api.activities:
                for entity in activity.mediaplayer_entities:
                    self._extra_state_attributes[entity.name] = entity.state

        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        toggle_activity = self.config_entry.options.get(REMOTE_ON_BEHAVIOR, None)
        if toggle_activity and toggle_activity != "No Action":
            for activity in self.coordinator.api.activities:
                if activity.name == toggle_activity:
                    await activity.turn_on()
                    self._attr_current_activity = activity.name
                    break
        self._attr_is_on = True
        return

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        if hasattr(self.coordinator.api, "activities"):
            for activity in self.coordinator.api.activities:
                if activity.is_on():
                    await activity.turn_off()
        self._attr_is_on = False

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
                await self.coordinator.api.send_remote_command(
                    device=kwargs.get("device"),
                    command=indv_command,
                    repeat=kwargs.get("num_repeats"),
                )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state()
        self.async_write_ha_state()
