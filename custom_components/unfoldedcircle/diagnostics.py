"""Diagnostics support for Unfolded Circle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator

TO_REDACT = {
    "apikey",
    "pin",
    "mac_address",
    "ip_address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: UnfoldedCircleRemoteCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][UNFOLDED_CIRCLE_COORDINATOR]
    return async_redact_data(coordinator.data, TO_REDACT)
