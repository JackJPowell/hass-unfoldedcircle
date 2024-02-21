"""Remote sensor platform for Unfolded Circle."""
import asyncio
from collections.abc import Iterable
import logging
from typing import Any, Mapping

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNFOLDED_CIRCLE_API, UNFOLDED_CIRCLE_COORDINATOR
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def init_device_data(remote):
    await remote.get_remotes()
    await remote.get_remote_codesets()
    await remote.get_docks()

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Platform."""
    remote = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_API]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    # Get Basic Device Information
    # Async task because it may raise timeouts
    asyncio.ensure_future(init_device_data(remote))

    new_devices = []
    new_devices.append(RemoteSensor(coordinator, remote))
    if new_devices:
        async_add_entities(new_devices)


class RemoteSensor(UnfoldedCircleEntity, RemoteEntity):
    """Remote Sensor."""

    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    _attr_icon = "mdi:remote"
    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = RemoteEntityFeature.ACTIVITY

    def __init__(self, coordinator, remote) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._remote = remote
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._remote.serial_number}_remote"

        # The name of the entity
        self._attr_name = f"{self._remote.name} Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False

        for activity in self._remote.activities:
            self._attr_activity_list.append(activity.name)
        self.update_state()

    @property
    def is_on(self) -> bool | None:
        return self.update_state()

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    def update_state(self) -> bool:
        self._attr_is_on = False
        self._attr_current_activity = None
        for activity in self._remote.activities:
            self._extra_state_attributes[activity.name] = activity._state
            if activity.is_on():
                self._attr_current_activity = activity.name
                self._attr_is_on = True
        for activity in self._remote.activities:
            for entity in activity.mediaplayer_entities:
                self._extra_state_attributes[entity._name] = entity.state
                if len(entity.source_list) > 0:
                    self._extra_state_attributes["Media Player :" +entity._name+" sources"] = ", ".join(entity.source_list)
                if entity.current_source is not None:
                    self._extra_state_attributes["Media Player :" +entity._name + " current source"] = entity.current_source

        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        # Nothing can be done here
        # self._attr_is_on = True
        return

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        for activity in self._remote.activities:
            if activity.is_on():
                await activity.turn_off()
        self._attr_is_on = False

    async def async_send_command(self, command: Iterable[str], **kwargs):
        """Send a remote command."""
        for indv_command in command:
            await self._remote.send_remote_command(
                device=kwargs.get("device"),
                command=indv_command,
                repeat=kwargs.get("num_repeats"),
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state()
        self.async_write_ha_state()
