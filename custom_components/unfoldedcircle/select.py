"""Select platform for Electrolux Status."""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import UnfoldedCircleRemoteCoordinator
from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR

import logging

from .entity import UnfoldedCircleEntity
from .pyUnfoldedCircleRemote.const import RemoteUpdateType

_LOGGER = logging.getLogger(__name__)

POWER_OFF_LABEL = "Power Off"


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    async_add_entities(
        SelectUCRemoteActivity(coordinator, activity_group) for activity_group in coordinator.api.activity_groups
    )


class SelectUCRemoteActivity(UnfoldedCircleEntity, SelectEntity):
    """Select entity class."""

    def __init__(self, coordinator, activity_group) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.activity_group = activity_group
        self._name = f"{self.coordinator.api.name} {activity_group.name}"
        self._attr_name = f"{self.coordinator.api.name} {activity_group.name}"
        self._attr_unique_id = f"{self.coordinator.api.serial_number}_{activity_group._id}"
        self._state = activity_group.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"
        self._activities: dict[str, any] = {POWER_OFF_LABEL: "OFF"}
        # _LOGGER.debug("Activity groups %s", self.activity_group.activities)
        for activity_id in self.activity_group.activities:
            for activity in coordinator.api.activities:
                if activity._id == activity_id:
                    self._activities[activity._name] = activity

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self.coordinator.subscribe_events["entity_activity"] = True
        self.coordinator.subscribe_events["activity_groups"] = True
        await super().async_added_to_hass()

    @property
    def should_poll(self) -> bool:
        return False

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

    @property
    def translation_key(self) -> str | None:
        return "activity_group"

    @property
    def current_option(self) -> str:
        for activity_name, activity in self._activities.items():
            if activity_name == POWER_OFF_LABEL:
                continue
            if activity.is_on():
                return activity_name
        return POWER_OFF_LABEL

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option == POWER_OFF_LABEL:
            for activity_name, activity in self._activities.items():
                if activity_name == POWER_OFF_LABEL:
                    continue
                if activity.state == "ON":
                    await activity.turn_off()
                    break
            return
        activity = self._activities.get(option, None)
        if activity is None:
            return
        await activity.turn_on()

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        return list(self._activities.keys())

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update only if activity changed
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
        except (KeyError, IndexError):
            _LOGGER.debug("Unfolded Circle Remote select _handle_coordinator_update error")
            return
        self._state = self.activity_group.state
        for activity_name, activity in self._activities.items():
            if activity_name == POWER_OFF_LABEL:
                continue
        self.async_write_ha_state()
