"""The Unfolded Circle Remote integration."""

from __future__ import annotations

import logging

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
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
