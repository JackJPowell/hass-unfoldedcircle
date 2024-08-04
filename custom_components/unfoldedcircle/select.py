"""Select platform for Unfolded Circle"""

import logging
from typing import Any, Mapping

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyUnfoldedCircleRemote.const import RemoteUpdateType

from .const import (
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
    UNFOLDED_CIRCLE_COORDINATOR,
)
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)

POWER_OFF_LABEL = "Power Off"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][
        UNFOLDED_CIRCLE_COORDINATOR
    ]
    # IF the option to suppress activity groups is true, skip adding activity groups
    if config_entry.options.get(CONF_SUPPRESS_ACTIVITIY_GROUPS, False) is False:
        async_add_entities(
            SelectUCRemoteActivity(coordinator, activity_group)
            for activity_group in coordinator.api.activity_groups
        )


class SelectUCRemoteActivity(UnfoldedCircleEntity, SelectEntity):
    """Select entity class."""

    def __init__(self, coordinator, activity_group) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.activity_group = activity_group
        self._attr_has_entity_name = True
        self._attr_name = f"{activity_group.name}"
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_{activity_group._id}"
        self._state = activity_group.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"
        self._extra_state_attributes = {}

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self.coordinator.subscribe_events["entity_activity"] = True
        self.coordinator.subscribe_events["activity_groups"] = True
        await super().async_added_to_hass()

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    @property
    def translation_key(self) -> str | None:
        return "activity_group"

    @property
    def current_option(self) -> str:
        for activity in self.activity_group.activities:
            if activity.is_on():
                return activity.name
        return POWER_OFF_LABEL

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option == POWER_OFF_LABEL:
            for activity in self.activity_group.activities:
                if activity.is_on():
                    await activity.turn_off()
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        for activity in self.activity_group.activities:
            if activity.name == option:
                await activity.turn_on()
                self._attr_current_option = option
                self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        option_list = [POWER_OFF_LABEL]
        for activity in self.activity_group.activities:
            option_list.append(activity.name)
        return option_list

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update only if activity changed
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
            self._extra_state_attributes = {}
        except (KeyError, IndexError):
            _LOGGER.debug(
                "Unfolded Circle Remote select _handle_coordinator_update error"
            )
            return
        self._state = self.activity_group.state
        for activity in self.activity_group.activities:
            if activity.is_on():
                for entity in activity.mediaplayer_entities:
                    self._extra_state_attributes[entity.name] = entity.state
        self.async_write_ha_state()
