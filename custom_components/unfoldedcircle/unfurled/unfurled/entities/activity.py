"""Activity and ActivityGroup domain classes."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from ..helpers.models import ActivityState

if TYPE_CHECKING:
    from ..remote import Remote
    from .media_player import MediaPlayerEntity

_LOGGER = logging.getLogger(__name__)


class Activity:
    """Represents a single Unfolded Circle activity."""

    def __init__(self, data: dict, remote: Remote) -> None:
        self._remote = remote
        self._id: str = data["entity_id"]
        self._name: str = remote.settings.get_text_for_locale(
            data.get("name", {}), default_text="Unnamed Activity"
        )
        self._state: str = data.get("attributes", {}).get("state", ActivityState.OFF)

        # Included entities (populated during full init)
        self._included_entities: list[dict] = []

        # Media player entities linked to this activity (populated from WS events)
        self._media_player_entities: list[MediaPlayerEntity] = []

        # Physical button → command mappings (populated during full init)
        self._volume_up_command: dict | None = None
        self._volume_down_command: dict | None = None
        self._volume_mute_command: dict | None = None
        self._play_pause_command: dict | None = None
        self._next_track_command: dict | None = None
        self._prev_track_command: dict | None = None
        self._power_command: dict | None = None
        self._stop_command: dict | None = None
        self._seek_command: dict | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Unique entity ID of the activity."""
        return self._id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return self._name

    @property
    def state(self) -> str:
        """Current state string (see :class:`~unfurled.models.ActivityState`)."""
        return self._state

    @property
    def is_on(self) -> bool:
        """``True`` when the activity state is ``ON``."""
        return self._state == ActivityState.ON

    @property
    def included_entities(self) -> list[dict]:
        """Raw list of entity descriptors included in this activity."""
        return self._included_entities

    @property
    def media_player_entities(self) -> list:
        """List of :class:`~unfurled.media_player.MediaPlayerEntity` objects for this activity."""
        return self._media_player_entities

    @property
    def has_media_players(self) -> bool:
        """``True`` when at least one media player entity is associated."""
        return bool(self._media_player_entities)

    # Button command shortcuts
    @property
    def volume_up_command(self) -> dict | None:
        """Mapped volume-up button command or ``None``."""
        return self._volume_up_command

    @property
    def volume_down_command(self) -> dict | None:
        """Mapped volume-down button command or ``None``."""
        return self._volume_down_command

    @property
    def volume_mute_command(self) -> dict | None:
        """Mapped volume-mute button command or ``None``."""
        return self._volume_mute_command

    @property
    def play_pause_command(self) -> dict | None:
        """Mapped play/pause button command or ``None``."""
        return self._play_pause_command

    @property
    def next_track_command(self) -> dict | None:
        """Mapped next-track button command or ``None``."""
        return self._next_track_command

    @property
    def prev_track_command(self) -> dict | None:
        """Mapped previous-track button command or ``None``."""
        return self._prev_track_command

    @property
    def power_command(self) -> dict | None:
        """Mapped power button command or ``None``."""
        return self._power_command

    @property
    def stop_command(self) -> dict | None:
        """Mapped stop button command or ``None``."""
        return self._stop_command

    @property
    def seek_command(self) -> dict | None:
        """Mapped seek button command or ``None``."""
        return self._seek_command

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._state = state

    def _apply_button_mapping(self, button: str, short_press: dict | None) -> None:
        """Apply a button→command mapping returned by the API."""
        match button:
            case "VOLUME_UP":
                self._volume_up_command = short_press
            case "VOLUME_DOWN":
                self._volume_down_command = short_press
            case "MUTE":
                self._volume_mute_command = short_press
            case "PLAY":
                self._play_pause_command = short_press
            case "NEXT":
                self._next_track_command = short_press
            case "PREV":
                self._prev_track_command = short_press
            case "POWER":
                self._power_command = short_press
            case "STOP":
                self._stop_command = short_press

    def add_media_player_entity(self, entity: MediaPlayerEntity) -> None:
        """Add a media player entity if not already tracked."""
        if not any(e.id == entity.id for e in self._media_player_entities):
            self._media_player_entities.append(entity)

    # ------------------------------------------------------------------
    # Remote commands
    # ------------------------------------------------------------------

    async def turn_on(self) -> None:
        """Turn on this activity."""
        await self._remote._ensure_awake()
        await self._remote.api.put_entity_command(self._id, "activity.on")
        self._state = ActivityState.ON

    async def turn_off(self) -> None:
        """Turn off this activity."""
        await self._remote._ensure_awake()
        await self._remote.api.put_entity_command(self._id, "activity.off")
        self._state = ActivityState.OFF

    async def edit(self, **options: object) -> None:
        """Patch activity options.  Currently supports ``prevent_sleep``."""
        body: dict = {}
        if "prevent_sleep" in options:
            body = {"options": {"prevent_sleep": bool(options["prevent_sleep"])}}
        if body:
            await self._remote.api.patch_activity(self._id, body)

    async def refresh(self) -> None:
        """Re-fetch activity state and included entities from the remote."""
        data = await self._remote.api.get_activity(self._id)
        self._state = data["attributes"]["state"]
        with contextlib.suppress(KeyError, TypeError):
            self._included_entities = data["options"]["included_entities"]


class ActivityGroup:
    """Represents a group of activities on the remote."""

    def __init__(
        self,
        group_id: str,
        name: str,
        remote: Remote,
        state: str,
    ) -> None:
        self._id = group_id
        self._name = name
        self._remote = remote
        self._state = state
        self.activities: list[Activity] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Unique activity-group identifier."""
        return self._id

    @property
    def name(self) -> str:
        """Display name for this activity group."""
        return self._name

    @property
    def state(self) -> str:
        """Aggregate state of the group (``ON`` when any member activity is on)."""
        return self._state

    @property
    def is_on(self) -> bool:
        """``True`` when at least one member activity is currently running."""
        return self._state == ActivityState.ON

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_activity(self, activity_id: str) -> Activity | None:
        """Return the member activity with the given ID, or ``None``."""
        return next((a for a in self.activities if a.id == activity_id), None)

    def contains(self, activity_id: str) -> bool:
        """Return ``True`` if an activity with the given ID is a member of this group."""
        return self.get_activity(activity_id) is not None

    def _recalculate_state(self) -> None:
        """Derive group state from member activity states."""
        self._state = (
            ActivityState.ON if any(a.is_on for a in self.activities) else ActivityState.OFF
        )

    async def refresh(self) -> None:
        """Refresh state for any currently-on activities in the group."""
        for activity in self.activities:
            if activity.is_on:
                await activity.refresh()
        self._recalculate_state()
