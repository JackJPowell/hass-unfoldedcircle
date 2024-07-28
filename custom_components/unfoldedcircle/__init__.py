"""The Unfolded Circle Remote integration."""

from __future__ import annotations
from typing import Any
import logging

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pyUnfoldedCircleRemote.remote import AuthenticationError, Remote

from .const import DOMAIN, UNFOLDED_CIRCLE_API, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Unfolded Circle Remote from a config entry."""

    try:
        remote_api = Remote(entry.data["host"], entry.data["pin"], entry.data["apiKey"])
        await remote_api.can_connect()
        await remote_api.get_remote_information()

    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(err) from err
    except Exception as ex:
        raise ConfigEntryNotReady(ex) from ex

    coordinator = UnfoldedCircleRemoteCoordinator(hass, remote_api)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        UNFOLDED_CIRCLE_COORDINATOR: coordinator,
        UNFOLDED_CIRCLE_API: remote_api,
    }

    # Extract activities and activity groups
    await coordinator.api.init()

    # Retrieve info from Remote
    # Get Basic Device Information
    await coordinator.async_config_entry_first_refresh()

    @callback
    def async_migrate_entity_entry(entry: er.RegistryEntry) -> dict[str, Any] | None:
        """Migrate Unfolded Circle entity entries.

        - Migrates old unique ID's to the new unique ID's
        """
        if (
            entry.domain != Platform.UPDATE
            and "ucr" not in entry.unique_id.lower()
            and "ucd" not in entry.unique_id.lower()
            and (entry.domain == Platform.SWITCH and "uc.main" not in entry.unique_id)
        ):
            new = f"{coordinator.api.model_number}_{entry.unique_id}"
            return {"new_unique_id": entry.unique_id.replace(entry.unique_id, new)}

        if entry.domain == Platform.UPDATE and "ucr" not in entry.unique_id.lower():
            new = f"{coordinator.api.model_number}_{coordinator.api.serial_number}_update_status"
            return {"new_unique_id": entry.unique_id.replace(entry.unique_id, new)}

        # No migration needed
        return None

    # Migrate unique ID -- Make the ID actually Unique.
    # Migrate Device Name -- Make the device name match the psn username
    # We can remove this logic after a reasonable period of time has passed.
    if entry.version == 1:
        await er.async_migrate_entries(hass, entry.entry_id, async_migrate_entity_entry)
        _migrate_device_identifiers(hass, entry.entry_id, coordinator)
        hass.config_entries.async_update_entry(entry, version=2)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    await zeroconf.async_get_async_instance(hass)
    await coordinator.init_websocket()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        coordinator: UnfoldedCircleRemoteCoordinator = hass.data[DOMAIN][
            entry.entry_id
        ][UNFOLDED_CIRCLE_COORDINATOR]
        await coordinator.close_websocket()
    except Exception as ex:
        _LOGGER.error("Unfolded Circle Remote async_unload_entry error: %s", ex)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Update Listener."""
    # TODO Should be ?
    # await async_unload_entry(hass, entry)
    # await async_setup_entry(hass, entry)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, self):
    """Migrate Entry Support"""
    return True


def _migrate_device_identifiers(
    hass: HomeAssistant, entry_id: str, coordinator
) -> None:
    """Migrate old device identifiers."""
    dev_reg = dr.async_get(hass)
    devices: list[dr.DeviceEntry] = dr.async_entries_for_config_entry(dev_reg, entry_id)
    for device in devices:
        old_identifier = list(next(iter(device.identifiers)))
        if (
            "ucr" not in old_identifier[1].lower()
            and "ucd" not in old_identifier[1].lower()
        ):
            new_identifier = {
                (DOMAIN, coordinator.api.model_number, coordinator.api.serial_number)
            }
            _LOGGER.debug(
                "migrate identifier '%s' to '%s'", device.identifiers, new_identifier
            )
            dev_reg.async_update_device(device.id, new_identifiers=new_identifier)
