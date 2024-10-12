"""Diagnostics support for Unfolded Circle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import UnfoldedCircleRemoteCoordinator
from . import UnfoldedCircleConfigEntry

TO_REDACT = {
    "apikey",
    "pin",
    "mac_address",
    "ip_address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UnfoldedCircleConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: UnfoldedCircleRemoteCoordinator = entry.runtime_data.coordinator
    return async_redact_data(coordinator.data, TO_REDACT)
