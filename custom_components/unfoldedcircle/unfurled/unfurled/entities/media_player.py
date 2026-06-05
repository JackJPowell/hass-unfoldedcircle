"""MediaPlayerEntity - a media player entity hosted on the remote."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..remote import Remote
    from .activity import Activity

_LOGGER = logging.getLogger(__name__)


class MediaPlayerEntity:
    """Represents a media player entity reported by the remote."""

    def __init__(self, entity_id: str, remote: Remote) -> None:
        self._id = entity_id
        self._remote = remote
        self._activity: Activity | None = None

        self._state = "OFF"
        self._name = entity_id
        self._source_list: list[str] = []
        self._current_source = ""
        self._media_title = ""
        self._media_artist = ""
        self._media_album = ""
        self._media_type = ""
        self._media_duration = 0
        self._media_position = 0
        self._media_position_updated_at: datetime | None = None
        self._muted = False
        self._volume = 0.0
        self._media_image_url: str | None = None
        self._entity_commands: list[str] = []
        self._initialized = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Unique entity ID."""
        return self._id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return self._name

    @property
    def state(self) -> str:
        """Current playback state string (e.g. ``"PLAYING"``, ``"OFF"``)."""
        return self._state

    @property
    def is_on(self) -> bool:
        """``True`` when the entity is not in ``OFF`` state."""
        return self._state != "OFF"

    @property
    def activity(self) -> Activity | None:
        """The parent :class:`~unfurled.activity.Activity` or ``None``."""
        return self._activity

    @property
    def source_list(self) -> list[str]:
        """Available input sources."""
        return self._source_list

    @property
    def current_source(self) -> str:
        """Currently selected input source."""
        return self._current_source

    @property
    def media_image_url(self) -> str | None:
        """URL of the current media artwork or ``None``."""
        return self._media_image_url

    @property
    def media_title(self) -> str:
        """Title of the currently playing media."""
        return self._media_title

    @property
    def media_artist(self) -> str:
        """Artist of the currently playing media."""
        return self._media_artist

    @property
    def media_album(self) -> str:
        """Album of the currently playing media."""
        return self._media_album

    @property
    def media_type(self) -> str:
        """Media type string (e.g. ``"music"``, ``"tvshow"``)."""
        return self._media_type

    @property
    def media_duration(self) -> int:
        """Duration of the current track in seconds."""
        return self._media_duration

    @property
    def media_position(self) -> int:
        """Current playback position in seconds."""
        return self._media_position

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Timestamp of the last position update."""
        return self._media_position_updated_at

    @property
    def muted(self) -> bool:
        """``True`` when the player is muted."""
        return self._muted

    @property
    def volume(self) -> float:
        """Current volume level (0.0 - 1.0)."""
        return self._volume

    @property
    def available_commands(self) -> list[str]:
        """List of command IDs supported by this entity."""
        return self._entity_commands

    @property
    def initialized(self) -> bool:
        """``True`` once the entity has received its first state update."""
        return self._initialized

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def update_attributes(self, attributes: dict) -> dict:
        """Apply attribute dict from a WebSocket event or API response.

        Returns a summary of what changed (useful for debug logging).
        """
        changed: dict = {"entity_id": self._id}

        def _set(attr: str, key: str, transform: Any = None) -> None:
            val = attributes.get(key)
            if val is not None:
                val = transform(val) if transform else val
                setattr(self, f"_{attr}", val)
                changed[key] = val

        _set("state", "state")
        _set("media_image_url", "media_image_url")
        _set("current_source", "source")
        _set("source_list", "source_list")
        _set("media_duration", "media_duration")
        _set("media_artist", "media_artist")
        _set("media_album", "media_album")
        _set("media_title", "media_title")
        _set("media_position", "media_position")
        _set("media_position_updated_at", "media_position_updated_at")
        _set("media_type", "media_type")
        _set("volume", "volume", float)

        # muted can be False (falsy) so check for explicit presence
        if "muted" in attributes:
            self._muted = bool(attributes["muted"])
            changed["muted"] = self._muted

        # If entity is "ON" by activity but reports OFF, honour activity state
        if self._state in (None, "OFF") and self._activity and self._activity.is_on:
            self._state = "ON"

        _LOGGER.debug("MediaPlayer %s attrs updated: %s", self._id, changed)
        return changed

    async def update_data(self, force: bool = False) -> None:
        """Fetch and apply the latest entity data from the remote."""
        if self._initialized and not force:
            return
        data = await self._remote.api.get_entity(self._id)
        self.update_attributes(data.get("attributes", {}))
        self._initialized = True

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _cmd(self, cmd_id: str, params: dict | None = None) -> None:
        await self._remote._ensure_awake()
        await self._remote.api.put_entity_command(self._id, cmd_id, params)

    async def _cmd_via_activity(self, direct_cmd: str, activity_cmd_attr: str) -> None:
        """Send a command, preferring the activity-mapped command if available."""
        await self._remote._ensure_awake()
        cmd = getattr(self._activity, activity_cmd_attr, None) if self._activity else None
        if cmd:
            entity_id = cmd.get("entity_id", self._id)
            await self._remote.api.put_entity_command(
                entity_id, cmd.get("cmd_id", direct_cmd), cmd.get("params")
            )
        else:
            await self._remote.api.put_entity_command(self._id, direct_cmd)

    async def turn_on(self) -> None:
        """Send a power-on command."""
        await self._cmd_via_activity("media_player.on", "power_command")
        self._state = "ON"

    async def turn_off(self) -> None:
        """Send a power-off command."""
        await self._cmd_via_activity("media_player.off", "power_command")
        self._state = "OFF"

    async def volume_up(self) -> None:
        """Increase the volume by one step."""
        await self._cmd_via_activity("media_player.volume_up", "volume_up_command")

    async def volume_down(self) -> None:
        """Decrease the volume by one step."""
        await self._cmd_via_activity("media_player.volume_down", "volume_down_command")

    async def mute_toggle(self) -> None:
        """Toggle mute on or off."""
        await self._cmd_via_activity("media_player.mute_toggle", "volume_mute_command")

    async def volume_set(self, volume: int) -> None:
        """Set the volume to an absolute level (0-100)."""
        await self._cmd("media_player.volume", {"volume": int(volume)})

    async def play_pause(self) -> None:
        """Toggle play / pause."""
        await self._cmd_via_activity("media_player.play_pause", "play_pause_command")

    async def stop(self) -> None:
        """Send a stop command."""
        await self._cmd_via_activity("media_player.stop", "stop_command")

    async def next_track(self) -> None:
        """Skip to the next track."""
        await self._cmd_via_activity("media_player.next", "next_track_command")

    async def previous_track(self) -> None:
        """Skip to the previous track."""
        await self._cmd_via_activity("media_player.previous", "prev_track_command")

    async def seek(self, position: float) -> None:
        """Seek to a position (in seconds) within the currently playing media."""
        await self._cmd("media_player.seek", {"media_position": position})

    async def select_source(self, source: str) -> None:
        """Switch the active input source."""
        await self._cmd("media_player.select_source", {"source": source})
        self._current_source = source
