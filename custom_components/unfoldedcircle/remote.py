"""Remote sensor platform for Unfolded Circle."""

import asyncio
from collections.abc import Iterable
from datetime import timedelta
from typing import Any, Mapping
import logging

import voluptuous as vol
from homeassistant.util import dt as dt_util

from homeassistant.components.remote import (
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service, entity_platform
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyUnfoldedCircleRemote.remote import AuthenticationError

from .const import (
    DOMAIN,
    LEARN_IR_COMMAND_SERVICE,
)
from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from . import UnfoldedCircleConfigEntry


_LOGGER: logging.Logger = logging.getLogger(__package__)

LEARNING_TIMEOUT = timedelta(seconds=30)

CREATE_CODESET_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("remote"): dict,
        vol.Required("ir_dataset"): dict,
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Platform."""
    coordinator = config_entry.runtime_data.coordinator
    dock_coordinators = config_entry.runtime_data.dock_coordinators
    platform = entity_platform.async_get_current_platform()

    async_add_entities([RemoteSensor(coordinator)])

    for dock_coordinator in dock_coordinators:
        async_add_entities([RemoteDockSensor(dock_coordinator)])

    @service.verify_domain_control(hass, DOMAIN)
    async def async_service_handle(service_call: ServiceCall) -> None:
        """Handle dispatched services."""

        assert platform is not None
        entities = await platform.async_extract_from_service(service_call)

        if not entities:
            return

        for entity in entities:
            assert isinstance(entity, RemoteDockSensor)

        if service_call.service == LEARN_IR_COMMAND_SERVICE:
            dock_coordinators = config_entry.runtime_data.dock_coordinators

            for coor in dock_coordinators:
                coordinator = coor
            ir = IR(coordinator, hass, data=service_call.data)
            await ir.async_learn_command()

    hass.services.async_register(
        DOMAIN,
        LEARN_IR_COMMAND_SERVICE,
        async_service_handle,
        CREATE_CODESET_SCHEMA,
    )


class RemoteDockSensor(UnfoldedCircleDockEntity, RemoteEntity):
    """Dock Remote Sensor"""

    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = (
        RemoteEntityFeature.ACTIVITY
        | RemoteEntityFeature.LEARN_COMMAND
        | RemoteEntityFeature.DELETE_COMMAND
    )

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_remote"
        self._attr_has_entity_name = True
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"

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


class RemoteSensor(UnfoldedCircleEntity, RemoteEntity):
    """Remote Sensor."""

    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = RemoteEntityFeature.ACTIVITY

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{coordinator.api.model_number}_{self.coordinator.api.serial_number}_remote"
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False
        self._attr_icon = "mdi:remote"

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
        # self._attr_is_on = False
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
        # Nothing can be done here
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


class IR:
    def __init__(self, coordinator, hass, data):
        self.coordinator = coordinator
        self.hass = hass
        self.data = data

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn a list of commands from a remote."""

        await self.coordinator.api.get_remotes_complete()

        name = self.data.get("remote").get("name")
        description = self.data.get("remote").get("description")
        icon = self.data.get("remote").get("icon")
        subdevice = self.data.get("ir_dataset").get("name")
        for command in self.data.get("ir_dataset").get("command"):
            try:
                code = await self._async_learn_ir_command(
                    command, subdevice, name, description, icon
                )

            except (AuthenticationError, OSError) as err:
                _LOGGER.error("Failed to learn '%s': %s", command, err)
                break

            except Exception as err:
                _LOGGER.error("Failed to learn '%s': %s", command, err)
                continue

    async def _async_learn_ir_command(self, command, device, name, description, icon):
        """Learn an infrared command."""

        try:
            await self.coordinator.api.start_ir_learning()

        except (Exception, OSError) as err:
            _LOGGER.debug("Failed to enter learning mode: %s", err)
            raise

        persistent_notification.async_create(
            self.hass,
            f"Press the '{command}' button.",
            title=f"Learn command for {device}",
            notification_id="learn_command",
        )

        is_existing_list = False
        remote_entity_id = ""
        for remote in self.coordinator.api.remotes_complete:
            if remote.get("options").get("ir").get("codeset").get("name") == device:
                remote_entity_id = remote.get("entity_id")
                is_existing_list = True

        if not is_existing_list:
            try:
                new_remote = await self.coordinator.api.create_remote(
                    name=name,
                    device=device,
                    description=description,
                    icon=icon,
                )
                remote_entity_id = new_remote.get("entity_id")
                # Refresh the list of remotes (We are shortcutting to save time. This
                # probably should just call the get_remotes_complete() method)
                await self.coordinator.api._remotes_complete.append(new_remote.copy())
            except Exception as ex:
                pass

        try:
            start_time = dt_util.utcnow()
            while (dt_util.utcnow() - start_time) < LEARNING_TIMEOUT:
                await asyncio.sleep(1)
                try:
                    if self.coordinator.api.learned_code:
                        ir_format = "HEX"
                        learned_code: str = self.coordinator.api.learned_code
                        if "0x" not in learned_code.lower():
                            ir_format = "PRONTO"

                        await self.coordinator.api.add_remote_command_to_codeset(
                            remote_entity_id,
                            command,
                            learned_code,
                            ir_format,
                        )
                        self.coordinator.api._learned_code = None
                        return self.coordinator.api._learned_code
                except AuthenticationError:
                    continue

            raise TimeoutError(
                f"No infrared code received within {LEARNING_TIMEOUT.total_seconds()} seconds"
            )

        finally:
            persistent_notification.async_dismiss(
                self.hass, notification_id="learn_command"
            )
