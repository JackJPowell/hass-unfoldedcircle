"""Outgoing media metadata and wake-up synchronization tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from custom_components.unfoldedcircle.const import CONF_RESIZE_MEDIA_IMAGES
from custom_components.unfoldedcircle.websocket import (
    UCWebsocketClient,
    _state_for_remote,
    ws_get_states,
    ws_subscribe_entities_event,
)
from homeassistant.core import Event, State

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def hass():
    """Only mock the HA services needed for outgoing state serialization."""
    hass = Mock()
    hass.config_entries.async_entries.return_value = []
    return hass


def media_state(playback="playing", **attributes):
    return State(
        "media_player.tv",
        playback,
        {
            "media_content_type": "tvshow",
            "media_season": 17,
            "media_episode": 10,
            "media_title": "Episode title",
            "media_artist": "Original artist",
            "entity_picture": "/art.jpg",
            "media_duration": 1301,
            "media_position": 628,
            "media_position_updated_at": (NOW - timedelta(seconds=30)).isoformat(),
            "supported_features": 2,
            **attributes,
        },
    )


def test_metadata_preserves_source_and_artwork(hass):
    state = media_state()
    original = dict(state.attributes)
    with patch(
        "custom_components.unfoldedcircle.websocket.dt_util.utcnow", return_value=NOW
    ):
        result = _state_for_remote(hass, state, None)
    attrs = result["attributes"]
    assert attrs["media_artist"] == "S17E10"
    assert attrs["media_title"] == "Episode title"
    assert attrs["entity_picture"] == "/art.jpg"
    assert attrs["media_duration"] == 1301
    assert attrs["media_position"] == 658
    assert attrs["media_position_updated_at"] == NOW.isoformat()
    assert attrs["supported_features"] == 2
    assert dict(state.attributes) == original


@pytest.mark.parametrize(
    ("values", "artist"),
    [
        ({"media_season": "0", "media_episode": "02"}, "S0E2"),
        ({"media_season": None}, "Original artist"),
        ({"media_episode": "unknown"}, "Original artist"),
        ({"media_episode": -1}, "Original artist"),
        ({"media_episode": True}, "Original artist"),
        ({"media_episode": 1.5}, "Original artist"),
        ({"media_content_type": "music"}, "Original artist"),
    ],
)
def test_episode_metadata_validation(hass, values, artist):
    assert (
        _state_for_remote(hass, media_state(**values), "remote")["attributes"][
            "media_artist"
        ]
        == artist
    )


@pytest.mark.parametrize(
    "playback", ["paused", "buffering", "idle", "off", "unavailable"]
)
def test_nonplaying_position_does_not_advance(hass, playback):
    state = media_state(playback)
    result = _state_for_remote(hass, state, "remote")["attributes"]
    assert result["media_position"] == 628
    assert (
        result["media_position_updated_at"]
        == state.attributes["media_position_updated_at"]
    )


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        "invalid",
        "2026-99-24T12:00:00Z",
        "2026-09-24T12:00:00",
        (NOW + timedelta(seconds=30)).isoformat(),
    ],
)
def test_unusable_timestamp_preserves_position(hass, timestamp):
    with patch(
        "custom_components.unfoldedcircle.websocket.dt_util.utcnow", return_value=NOW
    ):
        result = _state_for_remote(
            hass, media_state(media_position_updated_at=timestamp), "remote"
        )
    assert result["attributes"]["media_position"] == 628
    assert result["attributes"]["media_position_updated_at"] == timestamp


def test_position_clamped_to_duration(hass):
    with patch(
        "custom_components.unfoldedcircle.websocket.dt_util.utcnow", return_value=NOW
    ):
        result = _state_for_remote(hass, media_state(media_position=1299), "remote")
    assert result["attributes"]["media_position"] == 1301


def test_artwork_option_still_applies_with_metadata(hass):
    hass.config_entries.async_entries.return_value = [
        SimpleNamespace(options={"client_id": "remote", CONF_RESIZE_MEDIA_IMAGES: True})
    ]
    with patch("custom_components.unfoldedcircle.websocket.get_image_proxy") as proxy:
        proxy.return_value.url_for.return_value = "/resized.jpg"
        result = _state_for_remote(hass, media_state(), "remote")
    assert result["attributes"]["entity_picture"] == "/resized.jpg"
    assert result["attributes"]["media_artist"] == "S17E10"


def test_snapshot_and_live_events_use_same_metadata(hass):
    """Exercise actual subscription registration, ack ordering, and event callback."""
    client = object.__new__(UCWebsocketClient)
    client.hass = hass
    client._subscriptions = []
    client._subscriptions_changed = Mock()
    connection = Mock(subscriptions={})
    state = media_state()
    hass.states.get.side_effect = lambda entity_id: (
        state if entity_id == state.entity_id else None
    )
    msg = {
        "id": 42,
        "data": {
            "entities": [state.entity_id, "sensor.missing"],
            "client_id": "remote",
        },
    }
    with (
        patch(
            "custom_components.unfoldedcircle.websocket.UCWebsocketClient",
            return_value=client,
        ),
        patch(
            "custom_components.unfoldedcircle.websocket.async_track_state_change_event"
        ) as track,
        patch("custom_components.unfoldedcircle.websocket.update_config_entities"),
        patch(
            "custom_components.unfoldedcircle.websocket.dt_util.utcnow",
            return_value=NOW,
        ),
    ):
        ws_subscribe_entities_event(hass, connection, msg)
        assert connection.mock_calls[0][0] == "send_result"
        connection.send_event.assert_called_once()
        snapshot = connection.send_event.call_args.args[1]["data"]["new_state"]
        assert snapshot["attributes"]["media_position"] == 658
        assert snapshot["attributes"]["media_artist"] == "S17E10"
        callback = track.call_args.args[2]
        callback(
            Event(
                "state_changed",
                {"entity_id": state.entity_id, "old_state": None, "new_state": state},
            )
        )
        assert connection.send_event.call_args.args[1]["data"]["new_state"] == snapshot
        # Every new subscription gets a snapshot, even if HA state has not changed.
        connection.subscriptions[42]()
        assert not client._subscriptions
        ws_subscribe_entities_event(hass, connection, msg)
        assert connection.send_event.call_count == 3


def test_get_states_enriches_snapshot(hass):
    state = media_state()
    hass.states.get.return_value = state
    connection = Mock()
    with patch(
        "custom_components.unfoldedcircle.websocket.dt_util.utcnow", return_value=NOW
    ):
        ws_get_states(
            hass, connection, {"id": 1, "data": {"entity_ids": [state.entity_id]}}
        )
    attributes = connection.send_message.call_args.args[0]["result"][0]["attributes"]
    assert attributes["media_artist"] == "S17E10"
    assert attributes["media_position"] == 658


@pytest.mark.parametrize("position", [None, "628", True, -1, float("inf")])
def test_invalid_position_is_preserved(hass, position):
    result = _state_for_remote(hass, media_state(media_position=position), "remote")
    assert result["attributes"]["media_position"] == position


def test_non_media_and_removed_states_are_unchanged(hass):
    state = State("sensor.temperature", "20")
    assert _state_for_remote(hass, state, "remote") is state
    assert _state_for_remote(hass, None, "remote") is None


def test_datetime_position_timestamp(hass):
    with patch(
        "custom_components.unfoldedcircle.websocket.dt_util.utcnow", return_value=NOW
    ):
        result = _state_for_remote(
            hass,
            media_state(media_position_updated_at=NOW - timedelta(seconds=30)),
            "remote",
        )
    assert result["attributes"]["media_position"] == 658


@pytest.mark.parametrize("entity_id", ["media_player.tv", "media_player.other"])
def test_progress_does_not_add_seek_or_change_source(hass, entity_id):
    state = State(
        entity_id, "playing", dict(media_state(supported_features=1).attributes)
    )
    result = _state_for_remote(hass, state, "remote")
    assert result["attributes"]["supported_features"] == 1
    assert state.attributes["supported_features"] == 1


@pytest.mark.parametrize(
    ("duration", "position", "expected"),
    [
        (1301, 0, 1),
        (1301.5, 628.5, 1),
        (None, 628, 1),
        (1301, None, 1),
        (0, 0, 1),
        (-1, 628, 1),
        (1301, -1, 1),
        (True, 628, 1),
        (1301, True, 1),
        ("1301", 628, 1),
        (1301, "628", 1),
        (float("inf"), 628, 1),
        (1301, float("nan"), 1),
    ],
)
def test_progress_values_do_not_change_capabilities(hass, duration, position, expected):
    state = media_state(
        media_duration=duration, media_position=position, supported_features=1
    )
    result = _state_for_remote(hass, state, "remote")
    assert result["attributes"]["supported_features"] == expected


def test_existing_seek_is_preserved_without_progress(hass):
    state = media_state(media_duration=None, media_position=None, supported_features=3)
    assert (
        _state_for_remote(hass, state, "remote")["attributes"]["supported_features"]
        == 3
    )
