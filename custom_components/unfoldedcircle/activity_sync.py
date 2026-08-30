"""Synchronize activity states between configured Unfolded Circle remotes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging

from unfurled.helpers.exceptions import HTTPError

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_SYNCABLE_STATES = {"ON", "OFF"}


async def async_sync_activity_states(
    hass: HomeAssistant, source_coordinator, activity_ids: Iterable[str] | None = None
) -> None:
    """Copy selected activity states from one remote to every other remote."""
    source_ids = set(activity_ids) if activity_ids is not None else None
    activities = [
        activity
        for activity in source_coordinator.api.activities
        if (source_ids is None or activity.id in source_ids)
        and activity.state in _SYNCABLE_STATES
    ]
    if not activities:
        return

    targets = [
        entry.runtime_data.coordinator
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if entry.entry_id != source_coordinator.config_entry.entry_id
        and entry.runtime_data.coordinator.api.system.flags.entity_state_update_available
    ]
    await asyncio.gather(
        *(_async_sync_remote_activity_states(target, activities) for target in targets)
    )


async def _async_sync_remote_activity_states(target_coordinator, activities) -> None:
    """Synchronize activity states to one target remote."""
    for source_activity in activities:
        target_activity = target_coordinator.api.find_activity(source_activity.id)
        if target_activity is None:
            name_matches = [
                activity
                for activity in target_coordinator.api.activities
                if activity.name == source_activity.name
            ]
            target_activity = name_matches[0] if len(name_matches) == 1 else None
        if target_activity is None:
            _LOGGER.debug(
                "No matching activity for %s on %s",
                source_activity.name,
                target_coordinator.api.device.name,
            )
            continue
        if target_activity.state == source_activity.state:
            continue

        target_coordinator.expect_synced_activity_state(
            target_activity.id, source_activity.state
        )
        try:
            await target_activity.set_state(source_activity.state)
        except (
            HTTPError,
            OSError,
        ) as err:  # Keep syncing remaining activities/remotes.
            target_coordinator.clear_expected_synced_activity_state(target_activity.id)
            _LOGGER.warning(
                "Unable to sync activity %s to %s: %s",
                source_activity.name,
                target_coordinator.api.device.name,
                err,
            )
            continue

        # set_state updates Unfurled's cached activity state, but notifying the
        # coordinator makes the target's HA entities update immediately.
        target_coordinator.async_set_updated_data({"updated": True})
