"""The Unfolded Circle Remote integration."""

from __future__ import annotations
import logging
import copy
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pyUnfoldedCircleRemote.remote import AuthenticationError, Remote

from .const import DOMAIN, UC_HA_SYSTEM, UC_HA_TOKEN_ID
from .coordinator import (
    UnfoldedCircleRemoteCoordinator,
    UnfoldedCircleDockCoordinator,
    UnfoldedCircleConfigEntry,
    UnfoldedCircleRuntimeData,
)

from .helpers import (
    get_registered_websocket_url,
    async_create_issue_dock_password,
    async_create_issue_websocket_connection,
    validate_dock_password,
)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
    Platform.BUTTON,
    Platform.REMOTE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.MEDIA_PLAYER,
]

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant, entry: UnfoldedCircleConfigEntry
) -> bool:
    """Set up Unfolded Circle Remote from a config entry."""

    try:
        remote_api = Remote(entry.data["host"], entry.data["pin"], entry.data["apiKey"])
        await remote_api.validate_connection()
        await remote_api.get_remote_information()

    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(err) from err
    except ConnectionError as err:
        raise ConfigEntryNotReady(err) from err
    except Exception as ex:
        raise ConfigEntryNotReady(ex) from ex

    coordinator = UnfoldedCircleRemoteCoordinator(hass, remote_api, config_entry=entry)
    await coordinator.api.init()

    if entry.version < 3:
        dock_data = {}
        if "docks" in entry.data:
            for config_dock in entry.data["docks"]:
                dock = remote_api.get_dock_by_id(config_dock["id"])
                if dock:
                    if config_dock["password"] == "":
                        dock_data["password"] = "0000"
                    else:
                        dock_data["password"] = config_dock["password"]
                    dock_data["id"] = dock.id
                    dock_data["name"] = dock.name
                    if dock_data["password"] == "0000":
                        is_valid = await validate_dock_password(remote_api, dock_data)
                    if is_valid or dock_data["password"] != "0000":
                        create_subentry(hass, entry, dock_data)

                    hass.add_job(async_remove_device(hass, dock))

            copy_data = copy.deepcopy(dict(entry.data))
            copy_data["docks"] = []
            hass.config_entries.async_update_entry(entry, data=copy_data)
        hass.config_entries.async_update_entry(entry, version=3)

    docks = {}
    for subentry_id, subentry in entry.subentries.items():
        if subentry.data["password"] != "":
            dock = remote_api.get_dock_by_id(subentry.data["id"])
            dock_coordinator = UnfoldedCircleDockCoordinator(
                hass, dock, entry, subentry
            )
            try:
                await dock_coordinator.api.update()
                await dock_coordinator.async_config_entry_first_refresh()
                docks[subentry_id] = dock_coordinator
            except Exception as ex:
                _LOGGER.error(
                    "Could not initialize connection to dock %s (%s): %s",
                    dock.name,
                    dock.endpoint,
                    ex,
                )
        else:
            async_create_issue_dock_password(hass, dock, entry, subentry)

    entry.runtime_data = UnfoldedCircleRuntimeData(
        coordinator=coordinator, remote=remote_api, docks=docks
    )

    await coordinator.async_config_entry_first_refresh()

    if coordinator.api.external_entity_configuration_available:
        if not await get_registered_websocket_url(coordinator.api):
            # We haven't registered a new external system yet, raise issue
            async_create_issue_websocket_connection(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await zeroconf.async_get_async_instance(hass)
    await coordinator.init_websocket()
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: UnfoldedCircleConfigEntry
) -> bool:
    """Unload a config entry."""
    try:
        coordinator = entry.runtime_data.coordinator
        await coordinator.close_websocket()

        for dock in coordinator.api.docks:
            issue_registry.async_delete_issue(hass, DOMAIN, f"dock_password_{dock.id}")
            issue_registry.async_delete_issue(hass, DOMAIN, "websocket_connection")
    except Exception as ex:
        _LOGGER.error("Unfolded Circle Remote async_unload_entry error: %s", ex)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: UnfoldedCircleConfigEntry
) -> None:
    """Handle removal of an entry."""
    try:
        _LOGGER.debug("Removing remote from Home assistant for entry %s", entry)
        remote_api = Remote(entry.data["host"], entry.data["pin"], entry.data["apiKey"])
        try:
            results = await remote_api.delete_token_for_external_system(
                UC_HA_SYSTEM, UC_HA_TOKEN_ID
            )
            _LOGGER.debug("Results of token deletion : %s", results)
        except ConnectionError:
            _LOGGER.error(
                "Remote is unavailable, the HA token cannot be checked and won't be removed"
            )
        # TODO also delete HA token from HA
    except Exception as ex:
        _LOGGER.error("Unfolded Circle Remote async_remove_entry error: %s", ex)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle update."""
    await hass.config_entries.async_reload(entry.entry_id)


def create_subentry(
    hass: HomeAssistant, entry: UnfoldedCircleConfigEntry, dock: dict
) -> ConfigSubentry:
    """Create a subentry for a dock."""
    subentry = ConfigSubentry(
        data={
            "id": dock["id"],
            "name": dock["name"],
            "password": dock["password"],
        },
        subentry_id=dock["id"],
        subentry_type="dock",
        title=dock["name"],
        unique_id=f"{entry.unique_id}_{dock['id']}",
    )
    hass.config_entries.async_add_subentry(
        entry=entry,
        subentry=subentry,
    )


async def async_remove_device(hass: HomeAssistant, dock) -> None:
    """Remove the dock device from the device registry."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(
        identifiers={
            (
                DOMAIN,
                dock.model_name,
                dock.serial_number,
            )
        }
    )
    if device:
        dev_reg.async_remove_device(device.id)
