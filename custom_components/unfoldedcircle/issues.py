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


def dock_password_issue_id(entry_id: str, dock_id: str) -> str:
    """Return the entry-scoped issue ID for a dock password."""
    return f"dock_password_{entry_id}_{dock_id}"


def dock_unreachable_issue_id(entry_id: str, dock_id: str) -> str:
    """Return the entry-scoped issue ID for an unreachable dock."""
    return f"dock_unreachable_{entry_id}_{dock_id}"


def websocket_connection_issue_id(entry_id: str) -> str:
    """Return the entry-scoped issue ID for a WebSocket connection."""
    return f"websocket_connection_{entry_id}"


@callback
def async_delete_legacy_issues(hass: HomeAssistant) -> None:
    """Remove old issue IDs that cannot be linked to a config entry."""
    for (domain, issue_id), issue in list(
        issue_registry.async_get(hass).issues.items()
    ):
        if domain != DOMAIN or issue.config_entry_id is not None:
            continue
        if issue_id == "websocket_connection" or issue_id.startswith(
            ("dock_password_", "dock_unreachable_")
        ):
            issue_registry.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_create_issue_dock_password(
    hass: HomeAssistant, dock: Dock, entry: Any, subentry: Any
) -> None:
    """Create a repair issue for a dock with an empty password."""
    _LOGGER.debug("Empty dock password: %s", dock.device.name)
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        dock_password_issue_id(entry.entry_id, dock.device.id),
        config_entry_id=entry.entry_id,
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
        dock_unreachable_issue_id(entry.entry_id, dock.device.id),
        config_entry_id=entry.entry_id,
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
        websocket_connection_issue_id(entry.entry_id),
        config_entry_id=entry.entry_id,
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
def async_delete_issue_dock_unreachable(
    hass: HomeAssistant, entry_id: str, dock_id: str
) -> None:
    """Delete the unreachable-dock issue once the dock is available."""
    async_delete_issue(hass, dock_unreachable_issue_id(entry_id, dock_id))
