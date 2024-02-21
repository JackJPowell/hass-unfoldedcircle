"""Select platform for Electrolux Status."""
import base64
import re
import hashlib
from typing import Mapping, Any

from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerEntity, MediaType, \
    MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import UndefinedType

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR

import logging

from .entity import UnfoldedCircleEntity
from .pyUnfoldedCircleRemote.const import RemoteUpdateType
from .pyUnfoldedCircleRemote.remote import ActivityGroup, Activity, UCMediaPlayerEntity

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
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
        # | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SEEK  # TODO
)

STATES_MAP = {
    "OFF" : MediaPlayerState.OFF,
    "ON": MediaPlayerState.ON,
    "PLAYING": MediaPlayerState.PLAYING,
    "PAUSED": MediaPlayerState.PAUSED,
    "STANDBY": MediaPlayerState.STANDBY,
    "BUFFERING" : MediaPlayerState.BUFFERING
}

# SUPPORT_CLEAR_PLAYLIST # SUPPORT_SELECT_SOUND_MODE # SUPPORT_SHUFFLE_SET # SUPPORT_VOLUME_SET


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Use to setup entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]
    async_add_entities(
        MediaPlayerUCRemote(coordinator, activity_group) for activity_group in coordinator.api.activity_groups
    )


class MediaPlayerUCRemote(UnfoldedCircleEntity, MediaPlayerEntity):
    """Media player entity class."""

    _attr_supported_features = SUPPORT_MEDIA_PLAYER

    def __init__(self, coordinator, activity_group: ActivityGroup) -> None:
        """Initialize a switch."""
        super().__init__(coordinator)
        self.activity_group = activity_group
        self._name = f"{self.coordinator.api.name} {activity_group.name} player"
        self._attr_name = f"{self.coordinator.api.name} {activity_group.name} player"
        self._attr_unique_id = f"{self.coordinator.api.serial_number}_{activity_group._id}_mediaplayer"
        # self._state = activity_group.state
        self._extra_state_attributes = {}
        self._current_activity = None
        self._active_media_entities: [UCMediaPlayerEntity] = []
        self._active_media_entity: UCMediaPlayerEntity | None = None
        # self._attr_icon = "mdi:remote-tv"
        self._state = STATE_OFF
        self.update_state()

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self.coordinator.subscribe_events["entity_media_player"] = True
        await super().async_added_to_hass()

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_MEDIA_PLAYER

    def update_state(self):
        self._active_media_entities = []
        active_media_entity = self._active_media_entity
        if self._active_media_entity and not self._active_media_entity.is_on:
            _LOGGER.debug("Unfolded circle changed media player entity turned off for group %s : %s",
                          self.activity_group.name,
                          vars(self._active_media_entity))
            self._active_media_entity = None
        for activity in self.activity_group.activities:
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
                    if entity.state == "PLAYING" and self._active_media_entity.state != entity.state:
                        self._active_media_entity = entity
                        self._active_media_entities.append(entity)
                        continue
                    # Take this new one only if it has image URL or defined duration and the state is equal or better
                    if ((entity.media_image_url or entity.media_duration > 0)
                            and (self._active_media_entity.state == entity.state
                                 or entity.state == "PLAYING"
                                 or entity.state == "BUFFERING")):
                        self._active_media_entity = entity
                    self._active_media_entities.append(entity)
        self._extra_state_attributes = {}
        for entity in self._active_media_entities:
            self._extra_state_attributes[entity.name] = entity.state
        if self._active_media_entity:
            self._extra_state_attributes["Active media player"] = self._active_media_entity.name
        if self._active_media_entity and active_media_entity != self._active_media_entity:
            _LOGGER.debug("Unfolded circle changed active media player entity for group %s : %s",
                          self.activity_group.name,
                          vars(self._active_media_entity))

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_state_attributes

    @property
    def state(self):
        """Return the state of the device."""
        if self._active_media_entity:
            self._state = STATES_MAP.get(self._active_media_entity.state, STATE_OFF)
        else:
            self._state = STATE_OFF
        return self._state

    @property
    def name(self) -> str | UndefinedType | None:
        return self.activity_group.name+" media player"

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
        return None

    @property
    def media_image_hash(self) -> str | None:
        if self._active_media_entity and self._active_media_entity.media_image_url:
            return hashlib.sha256(str.encode(self._active_media_entity.media_image_url)).hexdigest()
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
                    result = re.search(r"data:([^;]+);base64,(.*)", self._active_media_entity.media_image_url)
                    if len(result.groups()) == 2:
                        mime_type = result.group(1)
                        bytes_data = base64.b64decode(result.group(2))
                        return bytes_data, mime_type
                except Exception as ex:
                    _LOGGER.debug("Unfolded circle error while decoding media artwork", ex)
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
        if self._active_media_entity:
            return self._active_media_entity.media_position_updated_at
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
        if self._active_media_entity:
            return self._active_media_entity.muted
        return False

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

    async def async_select_source(self, source):
        """Set the input source."""
        if self._active_media_entity:
            await self._active_media_entity.select_source(source)

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
        except (KeyError, IndexError):
            _LOGGER.debug("Unfolded Circle Remote MediaPlayer _handle_coordinator_update error")
            return
        # self._state = self.activity_group.state
        self.async_write_ha_state()
