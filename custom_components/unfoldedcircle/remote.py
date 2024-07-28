"""Remote sensor platform for Unfolded Circle."""

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from datetime import timedelta
from typing import Any, Mapping
import logging

import voluptuous as vol
from homeassistant.util import dt as dt_util

from homeassistant.const import ATTR_COMMAND
from homeassistant.components.remote import (
    RemoteEntity,
    RemoteEntityFeature,
    ATTR_ALTERNATIVE,
    ATTR_COMMAND_TYPE,
    ATTR_DEVICE,
    SERVICE_DELETE_COMMAND,
)
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import ToggleEntityDescription
from homeassistant.helpers.storage import Store
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    UNFOLDED_CIRCLE_COORDINATOR,
    UNFOLDED_CIRCLE_DOCK_COORDINATORS,
)
from .entity import UnfoldedCircleEntity, UnfoldedCircleDockEntity
from .pyUnfoldedCircleRemote.remote import AuthenticationError

_LOGGER: logging.Logger = logging.getLogger(__package__)

LEARNING_TIMEOUT = timedelta(seconds=30)
CODE_SAVE_DELAY = 15
FLAG_SAVE_DELAY = 15

COMMAND_TYPE_IR = "ir"
COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_COMMAND): vol.All(
            cv.ensure_list, [vol.All(cv.string, vol.Length(min=1))], vol.Length(min=1)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_LEARN_SCHEMA = COMMAND_SCHEMA.extend(
    {
        vol.Required(ATTR_DEVICE): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_COMMAND_TYPE, default=COMMAND_TYPE_IR): vol.In(
            COMMAND_TYPE_IR
        ),
        vol.Optional(ATTR_ALTERNATIVE, default=False): cv.boolean,
    }
)

SERVICE_DELETE_SCHEMA = COMMAND_SCHEMA.extend(
    {vol.Required(ATTR_DEVICE): vol.All(cv.string, vol.Length(min=1))}
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    dock_coordinators = hass.data[DOMAIN][config_entry.entry_id][
        UNFOLDED_CIRCLE_DOCK_COORDINATORS
    ]
    async_add_entities([RemoteSensor(coordinator)])

    for dock_coordinator in dock_coordinators:
        async_add_entities(
            [
                RemoteDockSensor(
                    dock_coordinator,
                    Store(
                        hass,
                        1,
                        f"unfoldedcircle_dock_{dock_coordinator.api.serial_number}_codes",
                    ),
                    Store(
                        hass,
                        1,
                        f"unfoldedcircle_dock_{dock_coordinator.api.serial_number}_flags",
                    ),
                )
            ]
        )


class RemoteDockSensor(UnfoldedCircleDockEntity, RemoteEntity):
    """Dock Remote Sensor"""

    _attr_icon = "mdi:remote"
    entity_description: ToggleEntityDescription
    _attr_supported_features: RemoteEntityFeature = (
        RemoteEntityFeature.ACTIVITY
        | RemoteEntityFeature.LEARN_COMMAND
        | RemoteEntityFeature.DELETE_COMMAND
    )

    def __init__(self, coordinator, codes, flags) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_remote"
        self._attr_has_entity_name = True
        self._attr_name = "Remote"
        self._attr_activity_list = []
        self._extra_state_attributes = {}
        self._attr_is_on = False

        self._code_storage = codes
        self._flag_storage = flags
        self._storage_loaded = False
        self._codes = {}
        self._flags = defaultdict(int)
        self._lock = asyncio.Lock()

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

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn a list of commands from a remote."""
        kwargs = SERVICE_LEARN_SCHEMA(kwargs)
        commands = kwargs[ATTR_COMMAND]
        command_type = kwargs[ATTR_COMMAND_TYPE]
        subdevice = kwargs[ATTR_DEVICE]
        toggle = kwargs[ATTR_ALTERNATIVE]
        # service = f"{DOMAIN}.{SERVICE_LEARN_COMMAND}"

        # if not self._attr_is_on:
        #     _LOGGER.warning(
        #         "%s canceled: %s entity is turned off", service, self.entity_id
        #     )
        #     return

        if not self._storage_loaded:
            await self._async_load_storage()

        async with self._lock:
            await self.coordinator.api.get_remotes_complete()

            should_store = False

            for command in commands:
                try:
                    code = await self._async_learn_ir_command(command, subdevice)

                except (AuthenticationError, OSError) as err:
                    _LOGGER.error("Failed to learn '%s': %s", command, err)
                    break

                except Exception as err:
                    _LOGGER.error("Failed to learn '%s': %s", command, err)
                    continue

                self._codes.setdefault(subdevice, {}).update({command: code})
                should_store = True

            if should_store:
                await self._code_storage.async_save(self._codes)

    async def _async_learn_ir_command(self, command, device):
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
                    name="Update Me",
                    device=device,
                    description="My Device",
                    icon="uc:movie",
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
                            remote_entity_id, command, learned_code, ir_format
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

    async def async_delete_command(self, **kwargs: Any) -> None:
        """Delete a list of commands from a remote."""
        kwargs = SERVICE_DELETE_SCHEMA(kwargs)
        commands = kwargs[ATTR_COMMAND]
        subdevice = kwargs[ATTR_DEVICE]
        service = f"{DOMAIN}.{SERVICE_DELETE_COMMAND}"

        if not self._attr_is_on:
            _LOGGER.warning(
                "%s canceled: %s entity is turned off",
                service,
                self.entity_id,
            )
            return

        if not self._storage_loaded:
            await self._async_load_storage()

        try:
            codes = self._codes[subdevice]
        except KeyError as err:
            err_msg = f"Device not found: {subdevice!r}"
            _LOGGER.error("Failed to call %s. %s", service, err_msg)
            raise ValueError(err_msg) from err

        cmds_not_found = []
        for command in commands:
            try:
                del codes[command]
            except KeyError:
                cmds_not_found.append(command)

        if cmds_not_found:
            if len(cmds_not_found) == 1:
                err_msg = f"Command not found: {cmds_not_found[0]!r}"
            else:
                err_msg = f"Commands not found: {cmds_not_found!r}"

            if len(cmds_not_found) == len(commands):
                _LOGGER.error("Failed to call %s. %s", service, err_msg)
                raise ValueError(err_msg)

            _LOGGER.error("Error during %s. %s", service, err_msg)

        # Clean up
        if not codes:
            del self._codes[subdevice]
            if self._flags.pop(subdevice, None) is not None:
                self._flag_storage.async_delay_save(self._get_flags, FLAG_SAVE_DELAY)

        self._code_storage.async_delay_save(self._get_codes, CODE_SAVE_DELAY)

    async def _async_load_storage(self):
        """Load code and flag storage from disk."""
        # Exception is intentionally not trapped to
        # provide feedback if something fails.
        self._codes.update(await self._code_storage.async_load() or {})
        self._flags.update(await self._flag_storage.async_load() or {})
        self._storage_loaded = True

    @callback
    def _get_codes(self):
        """Return a dictionary of codes."""
        return self._codes

    @callback
    def _get_flags(self):
        """Return a dictionary of toggle flags.

        A toggle flag indicates whether the remote should send an
        alternative code.
        """
        return self._flags


class RemoteSensor(UnfoldedCircleEntity, RemoteEntity):
    """Remote Sensor."""

    _attr_icon = "mdi:remote"
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
