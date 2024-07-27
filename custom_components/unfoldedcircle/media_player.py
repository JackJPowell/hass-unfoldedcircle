"""Media Player support for Unfolded Circle."""

import asyncio
import base64
import hashlib
import logging
import re
from typing import Any, Mapping

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import UndefinedType
from homeassistant.util import utcnow
from pyUnfoldedCircleRemote.const import RemoteUpdateType
from pyUnfoldedCircleRemote.remote import Activity, ActivityGroup, UCMediaPlayerEntity

from .const import (
    CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
    CONF_ACTIVITY_MEDIA_ENTITIES,
    CONF_GLOBAL_MEDIA_ENTITY,
    DOMAIN,
    UNFOLDED_CIRCLE_COORDINATOR,
)
from .entity import UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)

SUPPORT_MEDIA_PLAYER = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    # | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SEEK
)

STATES_MAP = {
    "OFF": MediaPlayerState.OFF,
    "ON": MediaPlayerState.ON,
    "PLAYING": MediaPlayerState.PLAYING,
    "PAUSED": MediaPlayerState.PAUSED,
    "STANDBY": MediaPlayerState.STANDBY,
    "BUFFERING": MediaPlayerState.BUFFERING,
}

# SUPPORT_CLEAR_PLAYLIST # SUPPORT_SELECT_SOUND_MODE # SUPPORT_SHUFFLE_SET # SUPPORT_VOLUME_SET
AUTOMATIC_ENTITY_SELECTION_LABEL = "Automatic selection"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    media_players = []
    # Enable the global media player entity for all activities if enabled by user
    if config_entry.options.get(CONF_GLOBAL_MEDIA_ENTITY, True):
        media_players.append(MediaPlayerUCRemote(coordinator))
    # Add additional media players (one per activity group) if the user option is enabled
    if config_entry.options.get(CONF_ACTIVITY_GROUP_MEDIA_ENTITIES, False):
        for activity_group in coordinator.api.activity_groups:
            media_players.append(
                MediaPlayerUCRemote(coordinator, activity_group=activity_group)
            )
    # Add additional media players (one per activity) if the user option is enabled
    if config_entry.options.get(CONF_ACTIVITY_MEDIA_ENTITIES, False):
        for activity in coordinator.api.activities:
            if activity.has_media_player_entities is True:
                media_players.append(
                    MediaPlayerUCRemote(coordinator, activity=activity)
                )
    async_add_entities(media_players)


class MediaPlayerUCRemote(UnfoldedCircleEntity, MediaPlayerEntity):
    """Media player entity class."""

    _attr_supported_features = SUPPORT_MEDIA_PLAYER

    def __init__(
        self,
        coordinator,
        activity_group: ActivityGroup = None,
        activity: Activity = None,
    ) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self.activity_group = activity_group
        self.activity = activity
        if activity_group is None and activity is None:
            self._attr_name = "Media Player"
            self._attr_unique_id = f"{self.coordinator.api.serial_number}_mediaplayer"
            self.activities = self.coordinator.api.activities
        elif activity is not None:
            self._attr_name = f"{activity.name} Media Player"
            self._attr_unique_id = (
                f"{self.coordinator.api.serial_number}_{activity.name}_mediaplayer"
            )
            self.activities = [activity]
        elif activity_group is not None:
            self._attr_name = f"{activity_group.name} Media Player"
            self._attr_unique_id = (
                f"{self.coordinator.api.serial_number}_{activity_group.id}_mediaplayer"
            )
            self.activities = self.activity_group.activities
        self._extra_state_attributes = {}
        self._current_activity = None
        self._active_media_entities: list[UCMediaPlayerEntity] = []
        self._active_media_entity: UCMediaPlayerEntity | None = None
        self._selected_media_entity: UCMediaPlayerEntity | None = None
        self._state = STATE_OFF
        self._volume_level = 0
        self.update_state()

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self.coordinator.subscribe_events["entity_media_player"] = True
        await super().async_added_to_hass()

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        # TODO handle available features based on media player capabilities + mapped buttons
        return self._attr_supported_features

    def update_state(self):
        """Sets the active media entity choosing the best choice if multiple are active"""
        # If the user has selected a given media player entity, stick to this one and do not
        # determine the right media player entity automatically
        self._active_media_entities = []
        active_media_entity = self._active_media_entity
        # With the added option 'Automatic Selection' this functionality is less relevant.
        # Let's trial this behavior
        # if self._selected_media_entity is not None and (
        #     self._selected_media_entity.is_on is False
        #     or (
        #         self._selected_media_entity.state
        #         not in ["PLAYING", "BUFFERING", "PAUSED"]
        #     )
        # ):
        #     self._selected_media_entity = None

        if self._active_media_entity and not self._active_media_entity.is_on:
            _LOGGER.debug(
                "Unfolded circle changed media player entity turned off: %s",
                vars(self._active_media_entity),
            )
            self._active_media_entity = None

        for activity in self.activities:
            if activity.is_on():
                self._current_activity = activity

                for entity in activity.mediaplayer_entities:
                    # Pick a media player entity : last one found or if it contains image media
                    # we suppose that this is the right one to take
                    if not entity.is_on:
                        self._active_media_entities.append(entity)
                        continue
                    if self._active_media_entity is None:
                        self._active_media_entity = entity
                        self._active_media_entities.append(entity)
                        continue
                    if (
                        entity.state == "PLAYING"
                        and self._active_media_entity.state != entity.state
                    ):
                        self._active_media_entity = entity
                        self._active_media_entities.append(entity)
                        continue
                    # Take this new one only if it has image URL
                    # or defined duration and the state is equal or better
                    if (entity.media_image_url or entity.media_duration > 0) and (
                        self._active_media_entity.state == entity.state
                        or entity.state == "PLAYING"
                        or entity.state == "BUFFERING"
                    ):
                        self._active_media_entity = entity
                    self._active_media_entities.append(entity)
        self._extra_state_attributes = {}
        for entity in self._active_media_entities:
            self._extra_state_attributes[entity.name] = entity.state
        if self._active_media_entity:
            self._extra_state_attributes["Active media player"] = (
                self._active_media_entity.name
            )
        if (
            self._active_media_entity
            and active_media_entity != self._active_media_entity
        ):
            _LOGGER.debug(
                "Unfolded circle changed active media player entity for group: %s :",
                vars(self._active_media_entity),
            )

        if self._selected_media_entity is not None:
            self._active_media_entity = self._selected_media_entity

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    @property
    def state(self):
        """Return the state of the device."""
        an_activity_is_on = False
        for activity in self.coordinator.api.activities:
            if activity.state == "ON" and activity.has_media_player_entities is True:
                an_activity_is_on = True
                break

        if an_activity_is_on is False:
            self._state = STATE_OFF
        elif self.activity is not None and self.activity.state == "OFF":
            self._state = STATE_OFF
        elif self._active_media_entity:
            self._state = STATES_MAP.get(self._active_media_entity.state, STATE_OFF)
        elif self.activity is not None and self.activity.state == "ON":
            self._state = STATE_ON
        elif (
            self.activity is None
            and self._active_media_entity is None
            and an_activity_is_on is True
        ):
            self._state = STATE_ON
        else:
            self._state = STATE_OFF
        return self._state

    @property
    def name(self) -> str | UndefinedType | None:
        if self.activity_group is None and self.activity is None:
            return f"{self.coordinator.api.name} Media Player"
        elif self.activity is not None:
            return f"{self.activity.name} Media Player"
        return f"{self.activity_group.name} Media Player"

    @property
    def source(self):
        """Return the current input source."""
        if self._active_media_entity:
            return self._active_media_entity.current_source
        return None

    @property
    def source_list(self):
        """List of available input sources."""
        if self._active_media_entity:
            return self._active_media_entity.source_list

    async def async_select_source(self, source):
        """Set the input source."""
        if self._active_media_entity:
            await self._active_media_entity.select_source(source)

    @property
    def sound_mode_list(self) -> list[str] | None:
        """Use sound mode to select alternate media player entities"""
        # if self._active_media_entity:
        sources: dict[str, any] = {AUTOMATIC_ENTITY_SELECTION_LABEL: True}
        for activity in self.activities:
            if activity.is_on():
                for entity in activity.mediaplayer_entities:
                    # if entity.state in ["PLAYING", "BUFFERING", "PAUSED"]:
                    if entity.state not in [
                        "UNAVAILABLE",
                        "OFF",
                    ]:
                        sources[entity.name] = entity
        return list(sources.keys())
        # return None

    @property
    def sound_mode(self) -> str | None:
        if self._selected_media_entity:
            return self._selected_media_entity.name
        return AUTOMATIC_ENTITY_SELECTION_LABEL

    async def async_select_sound_mode(self, sound_mode):
        """Switch the sound mode of the entity."""
        if sound_mode == AUTOMATIC_ENTITY_SELECTION_LABEL:
            self._selected_media_entity = None
            self.update_state()
            self.async_write_ha_state()
            return
        # if self._active_media_entity:
        for activity in self.activities:
            for entity in activity.mediaplayer_entities:
                if entity.name == sound_mode:
                    self._selected_media_entity = entity
                    self.update_state()
                    self.async_write_ha_state()
                    return

    @property
    def media_image_hash(self) -> str | None:
        if self._active_media_entity and self._active_media_entity.media_image_url:
            return hashlib.sha256(
                str.encode(self._active_media_entity.media_image_url)
            ).hexdigest()
        return None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        if self._active_media_entity and self._active_media_entity.media_image_url:
            if self._active_media_entity.media_image_url.startswith("data:"):
                return None
            else:
                return self._active_media_entity.media_image_url
        return None

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Fetch media image of current playing image."""
        if self._active_media_entity and self._active_media_entity.media_image_url:
            if self._active_media_entity.media_image_url.startswith("data:"):
                # Starts with data:image/png;base64,
                try:
                    result = re.search(
                        r"data:([^;]+);base64,(.*)",
                        self._active_media_entity.media_image_url,
                    )
                    if len(result.groups()) == 2:
                        mime_type = result.group(1)
                        bytes_data = base64.b64decode(result.group(2))
                        return bytes_data, mime_type
                except Exception as ex:
                    _LOGGER.debug(
                        "Unfolded circle error while decoding media artwork: %s", ex
                    )
            else:
                return await super().async_get_media_image()
        return None, None

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        if self._active_media_entity:
            if self._active_media_entity.media_type:
                if self._active_media_entity.media_type.lower() == "channel":
                    return MediaType.CHANNEL
                elif self._active_media_entity.media_type.lower() == "music":
                    return MediaType.MUSIC
                elif self._active_media_entity.media_type.lower() == "tvshow":
                    return MediaType.TVSHOW
                elif self._active_media_entity.media_type.lower() == "movie":
                    return MediaType.MOVIE
                elif self._active_media_entity.media_type.lower() == "video":
                    return MediaType.VIDEO
                elif self._active_media_entity.media_type.lower() == "radio":
                    return MediaType.PODCAST
                elif self._active_media_entity.media_album:
                    return MediaType.MUSIC
            return MediaType.VIDEO
        return None

    @property
    def media_content_id(self):
        """Content ID of current playing media."""
        return ""

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        if self._active_media_entity:
            return self._active_media_entity.media_duration
        return 0

    @property
    def media_position(self):
        """Position of current playing media in seconds."""
        if self._active_media_entity:
            return self._active_media_entity.media_position
        return 0

    @property
    def media_position_updated_at(self):
        """Last time status was updated."""
        if (
            self._active_media_entity
            and self._active_media_entity.media_position_updated_at
        ):
            return self._active_media_entity.media_position_updated_at.replace(
                tzinfo=utcnow().tzinfo
            )
        return None

    @property
    def media_title(self):
        """Title of current playing media."""
        if self._active_media_entity:
            return self._active_media_entity.media_title
        return None

    @property
    def media_artist(self):
        """Artist of current playing media."""
        if self._active_media_entity:
            return self._active_media_entity.media_artist
        return None

    @property
    def media_album_name(self):
        """Album of current playing media."""
        if self._active_media_entity:
            return self._active_media_entity.media_album

    @property
    def is_volume_muted(self) -> bool | None:
        """Boolean if volume is currently muted."""
        if (
            self._active_media_entity is not None
            and self._active_media_entity.activity is not None
            and self._active_media_entity.activity.volume_mute_command is not None
        ):
            entity_id = self._active_media_entity.activity.volume_mute_command.get(
                "entity_id"
            )
            for media_player in self._active_media_entities:
                if media_player.id == entity_id:
                    return media_player.muted
        if self._active_media_entity:
            return self._active_media_entity.muted
        return False

    @property
    def volume_level(self) -> float | None:
        if (
            self._active_media_entity is not None
            and self._active_media_entity.activity is not None
            and self._active_media_entity.activity.volume_mute_command is not None
        ):
            entity_id = self._active_media_entity.activity.volume_mute_command.get(
                "entity_id"
            )
            for media_player in self._active_media_entities:
                if media_player.id == entity_id:
                    return media_player.volume / 100
        if self._active_media_entity:
            return self._active_media_entity.volume / 100
        return 0

    async def async_turn_on(self):
        """Turn the media player on."""
        if self._active_media_entity:
            await self._active_media_entity.turn_on()

    async def async_turn_off(self):
        """Turn off media player."""
        if self._active_media_entity:
            await self._active_media_entity.turn_off()

    async def async_volume_up(self):
        """Volume up the media player."""
        if self._active_media_entity:
            await self._active_media_entity.volume_up()

    async def async_volume_down(self):
        """Volume down media player."""
        if self._active_media_entity:
            await self._active_media_entity.volume_down()

    async def async_mute_volume(self, mute):
        """Send mute command."""
        if self._active_media_entity:
            await self._active_media_entity.mute()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume command."""
        if self._active_media_entity:
            await self._active_media_entity.volume_set(volume * 100)

    async def async_media_play_pause(self):
        """Simulate play pause media player."""
        if self._active_media_entity:
            if self._active_media_entity.state == MediaPlayerState.PLAYING:
                return await self.async_media_pause()
            return await self.async_media_play()

    async def async_media_play(self):
        """Send play command."""
        if self._active_media_entity:
            await self._active_media_entity.play_pause()

    async def async_media_pause(self):
        """Send media pause command."""
        if self._active_media_entity:
            await self._active_media_entity.play_pause()

    async def async_media_stop(self):
        """Send media stop command."""
        if self._active_media_entity:
            await self._active_media_entity.stop()

    async def async_media_next_track(self):
        """Send next track command."""
        if self._active_media_entity:
            await self._active_media_entity.next()

    async def async_media_previous_track(self):
        """Send the previous track command."""
        if self._active_media_entity:
            await self._active_media_entity.previous()

    async def async_media_seek(self, position: float) -> None:
        """Seek position."""
        if self._active_media_entity:
            await self._active_media_entity.seek(position)
        return

    # @property
    # def translation_key(self) -> str | None:
    #     return "activity_group"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update only if activity changed
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
            self.update_state()
            if self._active_media_entity and not self._active_media_entity.initialized:
                _LOGGER.debug(
                    "Unfolded circle changed active media player entity not initialized, update it"
                )
                # return asyncio.run_coroutine_threadsafe(
                #     self._active_media_entity.update_data(), self.coordinator.hass.loop
                # ).result()
                asyncio.ensure_future(self._active_media_entity.update_data())
        except (KeyError, IndexError):
            _LOGGER.debug(
                "Unfolded Circle Remote MediaPlayer _handle_coordinator_update error"
            )
            return
        # self._state = self.activity_group.state
        self.async_write_ha_state()
        return super()._handle_coordinator_update()
