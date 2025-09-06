"""Remote sensor platform for Unfolded Circle."""

import asyncio
from datetime import timedelta
import re
from typing import Any, Mapping, Iterable
import logging

import voluptuous as vol
from voluptuous import Any as VolAny
from homeassistant.util import dt as dt_util

from homeassistant.components.remote import (
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service, entity_platform
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from .pyUnfoldedCircleRemote.remote import (
    AuthenticationError,
    InvalidButtonCommand,
    NoActivityRunning,
    RemoteIsSleeping,
    EntityCommandError,
)

from .const import (
    DOMAIN,
    LEARN_IR_COMMAND_SERVICE,
    SEND_IR_COMMAND_SERVICE,
    SEND_BUTTON_COMMAND_SERVICE,
    REMOTE_ON_BEHAVIOR,
)
from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from . import UnfoldedCircleConfigEntry
from .coordinator import UnfoldedCircleCoordinator, UnfoldedCircleDockCoordinator


_LOGGER: logging.Logger = logging.getLogger(__package__)

LEARNING_TIMEOUT = timedelta(seconds=30)

COMMAND_LIST = [
    "BACK",
    "HOME",
    "VOICE",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "GREEN",
    "DPAD_UP",
    "YELLOW",
    "DPAD_LEFT",
    "DPAD_MIDDLE",
    "DPAD_RIGHT",
    "RED",
    "DPAD_DOWN",
    "BLUE",
    "CHANNEL_UP",
    "CHANNEL_DOWN",
    "MUTE",
    "PREV",
    "PLAY",
    "PAUSE",
    "NEXT",
    "POWER",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Platform."""
    coordinator = config_entry.runtime_data.coordinator
    platform = entity_platform.async_get_current_platform()

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

    def get_ir_emitters(ir_emitters: list) -> str:
        return ir_emitters.get("name")

    create_codeset_schema = cv.make_entity_service_schema(
        {
            vol.Required("remote"): dict,
            vol.Required("ir_dataset"): dict,
            vol.Optional("dock"): SelectSelector(
                SelectSelectorConfig(
                    options=list(
                        map(
                            get_ir_emitters,
                            config_entry.runtime_data.remote.ir_emitters,
                        )
                    ),
                    sort=True,
                )
            ),
        },
        extra=vol.ALLOW_EXTRA,
    )

    send_codeset_schema = cv.make_entity_service_schema(
        {
            vol.Required("command"): VolAny(str, list[str]),
            vol.Optional("device"): str,
            vol.Optional("codeset"): str,
            vol.Optional("num_repeats"): str,
            vol.Optional("dock"): SelectSelector(
                SelectSelectorConfig(
                    options=list(
                        map(
                            get_ir_emitters,
                            config_entry.runtime_data.remote.ir_emitters,
                        )
                    ),
                    sort=True,
                )
            ),
            vol.Optional("port"): str,
        },
        extra=vol.ALLOW_EXTRA,
    )

    send_button_schema = cv.make_entity_service_schema(
        {
            vol.Required("command"): VolAny(str, list[str]),
            vol.Optional("num_repeats"): str,
            vol.Optional("activity"): str,
            vol.Optional("delay_secs"): str,
            vol.Optional("hold"): bool,
        },
        extra=vol.ALLOW_EXTRA,
    )

    @service.verify_domain_control(hass, DOMAIN)
    async def async_service_handle(service_call: ServiceCall) -> None:
        """Handle dispatched services."""
        dock_coordinator = None

        assert platform is not None
        entities = await platform.async_extract_from_service(service_call)

        if not entities:
            return

        for entity in entities:
            assert isinstance(entity, (RemoteSensor, RemoteDockSensor))

        for (
            _,
            coor,
        ) in config_entry.runtime_data.docks.items():
            if coor.api.name == service_call.data.get("dock"):
                dock_coordinator = coor
                break

        if service_call.service == LEARN_IR_COMMAND_SERVICE:
            ir = IR(None, dock_coordinator, hass, data=service_call.data)
            await ir.async_learn_command()

        if service_call.service == SEND_IR_COMMAND_SERVICE:
            coordinator = config_entry.runtime_data.coordinator

            ir = IR(coordinator, None, hass, data=service_call.data)
            await ir.async_send_command()

        if service_call.service == SEND_BUTTON_COMMAND_SERVICE:
            coordinator = config_entry.runtime_data.coordinator

            command = Command(coordinator, hass, data=service_call.data)
            await command.async_send()

    hass.services.async_register(
        DOMAIN,
        LEARN_IR_COMMAND_SERVICE,
        async_service_handle,
        create_codeset_schema,
    )

    hass.services.async_register(
        DOMAIN,
        SEND_IR_COMMAND_SERVICE,
        async_service_handle,
        send_codeset_schema,
    )

    hass.services.async_register(
        DOMAIN,
        SEND_BUTTON_COMMAND_SERVICE,
        async_service_handle,
        send_button_schema,
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


class IR:
    def __init__(
        self,
        coordinator: UnfoldedCircleCoordinator | None,
        dock_coordinator: UnfoldedCircleDockCoordinator | None,
        hass,
        data,
    ):
        self.coordinator = coordinator
        self.dock_coordinator = dock_coordinator
        self.hass = hass
        self.data = data

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn a list of commands from a remote."""

        await self.dock_coordinator.api.get_remotes_complete()

        name = self.data.get("remote").get("name")
        description = self.data.get("remote").get("description")
        icon = self.data.get("remote").get("icon")
        subdevice = self.data.get("ir_dataset").get("name")
        for command in self.data.get("ir_dataset").get("command"):
            try:
                await self._async_learn_ir_command(
                    command, subdevice, name, description, icon
                )

            except (AuthenticationError, OSError) as err:
                _LOGGER.error("Failed to learn '%s': %s", command, err)
                break

            except Exception as err:
                _LOGGER.error("Failed to learn '%s': %s", command, err)
                continue

        await self.dock_coordinator.api.stop_ir_learning()

    async def _async_learn_ir_command(self, command, device, name, description, icon):
        """Learn an infrared command."""

        try:
            await self.dock_coordinator.api.start_ir_learning()

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
        for remote in self.dock_coordinator.api.remotes_complete:
            if remote.get("options").get("ir").get("codeset").get("name") == device:
                remote_entity_id = remote.get("entity_id")
                is_existing_list = True

        if not is_existing_list:
            try:
                new_remote = await self.dock_coordinator.api.create_remote(
                    name=name,
                    device=device,
                    description=description,
                    icon=icon,
                )
                remote_entity_id = new_remote.get("entity_id")
                await self.dock_coordinator.api.get_remotes_complete()
            except Exception:
                pass

        try:
            start_time = dt_util.utcnow()
            while (dt_util.utcnow() - start_time) < LEARNING_TIMEOUT:
                await asyncio.sleep(1)
                try:
                    if self.dock_coordinator.api.learned_code:
                        ir_format = self.dock_coordinator.api.learned_code["format"]
                        ir_code = self.dock_coordinator.api.learned_code["value"]

                        await self.dock_coordinator.api.add_remote_command_to_codeset(
                            remote_entity_id,
                            command,
                            ir_code,
                            ir_format,
                        )
                        self.dock_coordinator.api._learned_code = None
                        return
                except AuthenticationError:
                    continue

            raise TimeoutError(
                f"No infrared code received within {LEARNING_TIMEOUT.total_seconds()} seconds"
            )

        finally:
            persistent_notification.async_dismiss(
                self.hass, notification_id="learn_command"
            )

    async def async_send_command(self, **kwargs: Any) -> None:
        """Send a list of commands from a remote."""

        await self.coordinator.api.get_remotes()
        ir_format = None
        code = None

        device = self.data.get("device")
        codeset = self.data.get("codeset")
        repeat = self.data.get("num_repeats", 0)
        dock_name = self.data.get("dock", None)
        port = self.data.get("port", None)

        if port:
            port = self.translate_port(port)

        commands: list[str] = []
        if type(self.data.get("command")) is list:
            commands = self.data.get("command")
        else:
            commands.append(self.data.get("command"))

        for command in commands:
            pattern = r"^\d+;0x[0-9A-Fa-f]+;\d+;\d+$"
            compiled_pattern = re.compile(pattern)

            if command.startswith("0000"):  # PRONTO
                ir_format = "PRONTO"
                code = command
                command = None
            elif compiled_pattern.search(command):  # HEX
                ir_format = "HEX"
                code = command
                command = None
            try:
                await self.coordinator.api.send_remote_command(
                    device,
                    command,
                    repeat,
                    codeset,
                    dock=dock_name,
                    port=port,
                    format=ir_format,
                    code=code,
                )
            except (AuthenticationError, OSError) as err:
                _LOGGER.error("Failed to send '%s': %s", command, err)
                break

            except Exception as err:
                _LOGGER.error("Failed to send '%s': %s", command, err)
                continue

    def translate_port(self, port_name) -> str:
        match port_name:
            case "Dock Top":
                return "2"
            case "Dock Bottom":
                return "1"
            case "Ext 1":
                return "4"
            case "Ext 2":
                return "8"
            case "Ext 1 & 2":
                return "12"
            case "Dock Bottom & Ext 1":
                return "5"
            case "Dock Bottom & Ext 2":
                return "9"
            case _:
                return port_name


class Command:
    def __init__(
        self,
        coordinator: UnfoldedCircleCoordinator | None,
        hass,
        data,
    ):
        self.coordinator = coordinator
        self.hass = hass
        self.data = data

    async def async_send(self, **kwargs):
        """Send a remote command."""
        commands: list[str] = []
        if type(self.data.get("command")) is list:
            commands = self.data.get("command")
        else:
            commands.append(self.data.get("command"))

        for indv_command in commands:
            if indv_command in COMMAND_LIST:
                if indv_command == "PAUSE":
                    indv_command = "PLAY"
                try:
                    await self.coordinator.api.send_button_command(
                        command=indv_command,
                        repeat=self.data.get("num_repeats"),
                        activity=self.data.get("activity"),
                        hold=self.data.get("hold"),
                        delay_secs=self.data.get("delay_secs"),
                    )
                except NoActivityRunning:
                    _LOGGER.error("No activity is running")
                except InvalidButtonCommand:
                    _LOGGER.error("Invalid button command: %s", indv_command)
                except RemoteIsSleeping:
                    _LOGGER.error("The remote did not repond to the wake command")
                except EntityCommandError as err:
                    _LOGGER.error("Failed to send command: %s", err.message)
