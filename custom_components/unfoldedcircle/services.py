"""Unfolded Circle services."""

import asyncio
from datetime import timedelta
import logging
import re
from typing import Any

import voluptuous as vol
from voluptuous import Any as VolAny

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import HomeAssistantError
from .coordinator import UnfoldedCircleConfigEntry
from .const import DOMAIN
from .coordinator import UnfoldedCircleCoordinator, UnfoldedCircleDockCoordinator
from .helpers import Command
from pyUnfoldedCircleRemote.remote import AuthenticationError

_LOGGER: logging.Logger = logging.getLogger(__package__)

LEARNING_TIMEOUT = timedelta(seconds=30)
UPDATE_ACTIVITY_SERVICE = "update_activity"
LEARN_IR_COMMAND_SERVICE = "learn_ir_command"
SEND_IR_COMMAND_SERVICE = "send_ir_command"
SEND_BUTTON_COMMAND_SERVICE = "send_button_command"
INHIBIT_STANDBY_SERVICE = "inhibit_standby"

INHIBIT_STANDBY_SERVICE_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("duration"): int,
        vol.Optional("why", default="User Action"): str,
    }
)

PREVENT_SLEEP_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional("prevent_sleep", default=False): cv.boolean}
)

SEND_BUTTON_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("command"): VolAny(str, list[str]),
        vol.Optional("num_repeats"): str,
        vol.Optional("activity"): str,
        vol.Optional("delay_secs"): str,
        vol.Optional("hold"): bool,
    },
    extra=vol.ALLOW_EXTRA,
)

CREATE_CODESET_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("remote"): dict,
        vol.Required("ir_dataset"): dict,
        vol.Optional("dock"): str,
    },
    extra=vol.ALLOW_EXTRA,
)

SEND_CODESET_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("command"): VolAny(str, list[str]),
        vol.Optional("device"): str,
        vol.Optional("codeset"): str,
        vol.Optional("num_repeats"): str,
        vol.Optional("dock"): str,
        vol.Optional("port"): str,
    },
    extra=vol.ALLOW_EXTRA,
)


SUPPORTED_SERVICES = (
    INHIBIT_STANDBY_SERVICE,
    UPDATE_ACTIVITY_SERVICE,
    SEND_BUTTON_COMMAND_SERVICE,
    LEARN_IR_COMMAND_SERVICE,
    SEND_IR_COMMAND_SERVICE,
)
SERVICE_TO_SCHEMA = {
    INHIBIT_STANDBY_SERVICE: INHIBIT_STANDBY_SERVICE_SCHEMA,
    UPDATE_ACTIVITY_SERVICE: PREVENT_SLEEP_SCHEMA,
    SEND_BUTTON_COMMAND_SERVICE: SEND_BUTTON_SCHEMA,
    LEARN_IR_COMMAND_SERVICE: CREATE_CODESET_SCHEMA,
    SEND_IR_COMMAND_SERVICE: SEND_CODESET_SCHEMA,
}


@callback
def async_setup_services(
    hass: HomeAssistant, config_entry: UnfoldedCircleConfigEntry
) -> None:
    """Set up services for Unfolded Circle integration."""

    services = {
        INHIBIT_STANDBY_SERVICE: async_inhibit_standby,
        UPDATE_ACTIVITY_SERVICE: async_prevent_sleep,
        SEND_BUTTON_COMMAND_SERVICE: async_service_handle,
        LEARN_IR_COMMAND_SERVICE: async_service_handle,
        SEND_IR_COMMAND_SERVICE: async_service_handle,
    }

    async def async_call_unfolded_circle_service(service_call: ServiceCall) -> None:
        """Call correct Unfolded Circle service."""
        await services[service_call.service](hass, service_call)

    for service in SUPPORTED_SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            async_call_unfolded_circle_service,
            schema=SERVICE_TO_SCHEMA.get(service),
        )


async def async_inhibit_standby(
    hass: HomeAssistant,
    service_call: ServiceCall,
) -> None:
    """Inhibit standby on the Unfolded Circle Remote."""

    config_entry = get_config_entry_by_entity_id(hass, service_call)
    duration = service_call.data["duration"]
    if duration is None:
        return

    why = service_call.data["why"]
    if why is None:
        why = "User Requested"

    inhibitors = (
        await config_entry.runtime_data.coordinator.api.get_standby_inhibitors()
    )
    length = len(inhibitors)
    inhibitor_id = f"HA{length}"

    await config_entry.runtime_data.coordinator.api.set_standby_inhibitor(
        inhibitor_id, "Home Assistant", why=why, delay=duration
    )


async def async_prevent_sleep(
    hass: HomeAssistant,
    service_call: ServiceCall,
) -> None:
    """Handle dispatched services."""

    config_entry = get_config_entry_by_entity_id(hass, service_call)
    entity_registry = er.async_get(hass)
    for selected_entity in service_call.data.get("entity_id", []):
        entities = [
            entity
            for entity in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
            if entity.entity_id == selected_entity
        ]
        if not entities:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="activity_not_found",
            )

        for entity in entities:
            if service_call.service == UPDATE_ACTIVITY_SERVICE:
                coordinator = config_entry.runtime_data.coordinator
                await coordinator.api.get_activity_by_id(entity.unique_id).edit(
                    service_call.data
                )


async def async_service_handle(
    hass: HomeAssistant,
    service_call: ServiceCall,
) -> None:
    """Handle dispatched services."""
    dock_coordinator = None
    dock_name = None
    config_entry = get_config_entry_by_entity_id(hass, service_call)

    # If a dock is specified in the service call, use that one
    if "dock" in service_call.data:
        dock_name = service_call.data.get("dock")
    # If there's only one dock, use that one
    elif len(config_entry.runtime_data.docks.items()) == 1:
        dock_name = next(iter(config_entry.runtime_data.docks.values())).api.name
    else:
        # If there are multiple docks, and none is specified, we can't proceed
        if service_call.service == LEARN_IR_COMMAND_SERVICE:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_dock",
            )

    for _, coor in config_entry.runtime_data.docks.items():
        if coor.api.name == dock_name:
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
        await self.dock_coordinator.api.get_remotes_complete()
        for remote in self.dock_coordinator.api.remotes_complete:
            if remote.get("options").get("ir").get("codeset").get("name") == device:
                remote_entity_id = remote.get("entity_id")
                is_existing_list = True

        if not is_existing_list:
            # First check the codeset isn't already created
            await self.dock_coordinator.api.get_custom_codesets()
            for codeset in self.dock_coordinator.api.codesets:
                if codeset.get("device") == device:
                    # delete the codeset, if it exists but isn't assigned to a remote
                    await self.dock_coordinator.api.delete_custom_codeset(
                        codeset.get("device_id")
                    )
                    break

            try:
                new_remote = await self.dock_coordinator.api.create_remote(
                    name=name,
                    device=device,
                    description=description,
                    icon=icon,
                )
                remote_entity_id = new_remote.get("entity_id")
                await self.dock_coordinator.api.get_remotes_complete()
            except Exception as err:
                _LOGGER.error("Failed to create new remote: %s", err)
                raise

        try:
            start_time = dt_util.utcnow()
            self.dock_coordinator.api._learned_code = None
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
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="failed_to_send_command",
                ) from err

            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="failed_to_send_command",
                ) from err

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


def get_config_entry_by_entity_id(
    hass: HomeAssistant, service_call: ServiceCall
) -> UnfoldedCircleConfigEntry | None:
    """Return the config entry for the given entity_id"""

    config_entries: list[UnfoldedCircleConfigEntry] = (
        hass.config_entries.async_loaded_entries(DOMAIN)
    )

    if "entity_id" in service_call.data:
        for config_entry in config_entries:
            entity_registry = er.async_get(hass)
            for selected_entity in service_call.data.get("entity_id", []):
                for entity in er.async_entries_for_config_entry(
                    entity_registry, config_entry.entry_id
                ):
                    if entity.entity_id == selected_entity:
                        return config_entry
    elif "device_id" in service_call.data:
        for config_entry in config_entries:
            entity_registry = er.async_get(hass)
            for selected_device in service_call.data.get("device_id", []):
                for device_id in er.async_entries_for_device(
                    entity_registry, selected_device
                ):
                    if device_id.device_id == selected_device:
                        return config_entry
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="unknown_config_entry",
    )
