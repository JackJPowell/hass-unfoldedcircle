"""The Unfolded Circle Remote integration."""
from __future__ import annotations

from pyUnfoldedCircleRemote.remote import Remote
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, UNFOLDED_CIRCLE_API, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
    Platform.BUTTON,
    Platform.REMOTE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Unfolded Circle Remote from a config entry."""

    remote_api = Remote(entry.data["host"], entry.data["pin"], entry.data["apiKey"])
    coordinator = UnfoldedCircleRemoteCoordinator(hass, remote_api)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        UNFOLDED_CIRCLE_COORDINATOR: coordinator,
        UNFOLDED_CIRCLE_API: remote_api,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    await zeroconf.async_get_async_instance(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Update Listener."""
    await hass.config_entries.async_reload(entry.entry_id)
