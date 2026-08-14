"""Home Assistant repair issue helpers for the Unfolded Circle integration."""

from __future__ import annotations

import logging
from typing import Any

from unfurled.dock import Dock

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_LEARN_MORE_URL = "https://github.com/jackjpowell/hass-unfoldedcircle"


@callback
def async_create_issue_dock_password(
    hass: HomeAssistant, dock: Dock, entry: Any, subentry: Any
) -> None:
    """Create a repair issue for a dock with an empty password."""
    _LOGGER.debug("Empty dock password: %s", dock.device.name)
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        f"dock_password_{dock.device.id}",
        breaks_in_ha_version=None,
        data={
            "id": dock.device.id,
            "name": dock.device.name,
            "config_entry": entry,
            "subentry": subentry,
        },
        is_fixable=True,
        is_persistent=False,
        learn_more_url=_LEARN_MORE_URL,
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="dock_password",
        translation_placeholders={"name": dock.device.name},
    )


@callback
def async_create_issue_dock_unreachable(
    hass: HomeAssistant, dock: Dock, entry: Any, subentry: Any, error: Exception
) -> None:
    """Create a repair issue for an unreachable dock."""
    _LOGGER.warning("Dock unreachable: %s - %s", dock.device.name, error)
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        f"dock_unreachable_{dock.device.id}",
        breaks_in_ha_version=None,
        data={
            "id": dock.device.id,
            "name": dock.device.name,
            "config_entry": entry,
            "subentry": subentry,
        },
        is_fixable=False,
        is_persistent=False,
        learn_more_url=_LEARN_MORE_URL,
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="dock_unreachable",
        translation_placeholders={"name": dock.device.name, "error": str(error)},
    )


@callback
def async_create_issue_websocket_connection(
    hass: HomeAssistant, entry: Any, coordinator: Any
) -> None:
    """Create a repair issue for a remote WebSocket connection."""
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        "websocket_connection",
        breaks_in_ha_version=None,
        data={"config_entry": entry, "name": coordinator.api.device.name},
        is_fixable=True,
        is_persistent=False,
        learn_more_url=_LEARN_MORE_URL,
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="websocket_connection",
        translation_placeholders={"name": coordinator.api.device.name},
    )


@callback
def async_delete_issue(hass: HomeAssistant, issue_id: str) -> None:
    """Delete an integration repair issue by its ID."""
    issue_registry.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_delete_issue_dock_unreachable(hass: HomeAssistant, dock_id: str) -> None:
    """Delete the unreachable-dock issue once the dock is available."""
    async_delete_issue(hass, f"dock_unreachable_{dock_id}")
