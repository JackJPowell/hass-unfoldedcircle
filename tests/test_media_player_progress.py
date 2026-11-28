"""Regression coverage for remote media progress values (issue #191)."""

from types import SimpleNamespace

import pytest
from unfurled.entities.media_player import MediaPlayerEntity

from custom_components.unfoldedcircle.media_player import MediaPlayerUCRemote


@pytest.mark.parametrize(
    ("duration", "expected_duration", "selected"),
    [
        ("", 0, False),
        (None, 0, False),
        ("unknown", 0, False),
        ("120.5", 120.5, True),
        (120.5, 120.5, True),
    ],
)
def test_remote_progress_does_not_interrupt_player_updates(
    duration, expected_duration, selected
):
    """Use actual unfurled entities to exercise the failing selection comparison."""
    first = MediaPlayerEntity("media_player.first", None)
    first.update_attributes({"state": "PLAYING"})
    tv_audio = MediaPlayerEntity("media_player.sonos", None)
    tv_audio.update_attributes(
        {
            "state": "PLAYING",
            "media_title": "TV Audio",
            "media_duration": duration,
            "media_position": "0",
        }
    )
    activity = SimpleNamespace(is_on=True, media_player_entities=[first, tv_audio])
    player = object.__new__(MediaPlayerUCRemote)
    player.activities = [activity]
    player._active_media_entity = first
    player._selected_media_entity = None

    player.update_state()

    assert tv_audio.media_duration == expected_duration
    assert player._active_media_entity is (tv_audio if selected else first)
    assert len(player._active_media_entities) == 2

    # A later update must still refresh metadata and honor manual selection.
    player._selected_media_entity = tv_audio
    tv_audio.update_attributes({"media_title": "Updated TV Audio"})
    player.update_state()

    assert player.media_title == "Updated TV Audio"
    assert player.media_duration == expected_duration
    assert player.media_position == 0
