"""Regression coverage for starting activities from media player entities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from unfurled.helpers.exceptions import HTTPError

from custom_components.unfoldedcircle.const import REMOTE_ON_BEHAVIOR
from custom_components.unfoldedcircle.media_player import MediaPlayerUCRemote
from homeassistant.exceptions import HomeAssistantError


def make_activity(name: str, *, is_on: bool = False, has_media_players: bool = True):
    return SimpleNamespace(
        id=f"activity.{name.lower()}",
        name=name,
        is_on=is_on,
        has_media_players=has_media_players,
        turn_on=AsyncMock(),
    )


def make_player(
    activities,
    *,
    activity=None,
    preferred=None,
    previous=None,
    media_entity=None,
):
    player = object.__new__(MediaPlayerUCRemote)
    player.activities = activities
    player.activity = activity
    player._current_activity = previous
    player._active_media_entity = media_entity
    player.coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={REMOTE_ON_BEHAVIOR: preferred})
    )
    return player


@pytest.mark.asyncio
async def test_activity_player_starts_off_activity_even_with_selected_device():
    activity = make_activity("TV")
    device = SimpleNamespace(turn_on=AsyncMock())
    player = make_player([activity], activity=activity, media_entity=device)

    await player.async_turn_on()

    activity.turn_on.assert_awaited_once_with()
    device.turn_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_activity_keeps_device_power_behavior():
    activity = make_activity("TV", is_on=True)
    device = SimpleNamespace(turn_on=AsyncMock())
    player = make_player([activity], activity=activity, media_entity=device)

    await player.async_turn_on()

    device.turn_on.assert_awaited_once_with()
    activity.turn_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_player_starts_configured_activity():
    tv = make_activity("TV")
    music = make_activity("Music")
    player = make_player([tv, music], preferred=music.id)

    await player.async_turn_on()

    music.turn_on.assert_awaited_once_with()
    tv.turn_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_media_activity_does_not_block_starting_media_activity():
    lights = make_activity("Lights", is_on=True, has_media_players=False)
    tv = make_activity("TV")
    player = make_player([lights, tv], preferred=lights.name)

    await player.async_turn_on()

    tv.turn_on.assert_awaited_once_with()
    lights.turn_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_player_restarts_last_activity_when_default_is_outside_group():
    tv = make_activity("TV")
    music = make_activity("Music")
    player = make_player([tv, music], preferred="Radio", previous=tv)

    await player.async_turn_on()

    tv.turn_on.assert_awaited_once_with()
    music.turn_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_activity_group_starts_its_only_activity():
    activity = make_activity("TV")
    player = make_player([activity])

    await player.async_turn_on()

    activity.turn_on.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_ambiguous_group_reports_why_it_cannot_start():
    player = make_player([make_activity("TV"), make_activity("Music")])

    with pytest.raises(HomeAssistantError, match="no activity to start"):
        await player.async_turn_on()


@pytest.mark.asyncio
async def test_activity_start_failure_is_reported_to_home_assistant():
    activity = make_activity("TV")
    activity.turn_on.side_effect = HTTPError(503, "remote unavailable")
    player = make_player([activity], activity=activity)

    with pytest.raises(HomeAssistantError, match="Failed to start activity TV"):
        await player.async_turn_on()
