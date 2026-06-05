"""Tests for the Activity and ActivityGroup classes."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from unfurled import Remote
from unfurled.entities.activity import Activity, ActivityGroup
from unfurled.helpers.models import ActivityState

BASE_URL = "http://192.168.1.10/api/"
API_KEY = "test-key"


@pytest.fixture
def remote():
    return Remote(BASE_URL, api_key=API_KEY)


@pytest.fixture
def on_activity(remote):
    return Activity(
        {"entity_id": "act-001", "name": {"en": "Watch TV"}, "attributes": {"state": "ON"}},
        remote,
    )


@pytest.fixture
def off_activity(remote):
    return Activity(
        {"entity_id": "act-002", "name": {"en": "Listen to Music"}, "attributes": {"state": "OFF"}},
        remote,
    )


class TestActivityProperties:
    def test_id(self, on_activity: Activity):
        assert on_activity.id == "act-001"

    def test_name_from_locale_dict(self, on_activity: Activity):
        assert on_activity.name == "Watch TV"

    def test_is_on_true_when_state_on(self, on_activity: Activity):
        assert on_activity.is_on is True

    def test_is_on_false_when_state_off(self, off_activity: Activity):
        assert off_activity.is_on is False

    def test_state_property(self, on_activity: Activity):
        assert on_activity.state == ActivityState.ON

    def test_set_state_updates_is_on(self, on_activity: Activity):
        assert on_activity.is_on is True
        on_activity._set_state("OFF")
        assert on_activity.is_on is False


class TestActivityButtonMapping:
    def test_apply_button_mapping_volume_up(self, off_activity: Activity):
        mapping = {"cmd_id": "media_player.volume_up", "entity_id": "media_player.tv"}
        off_activity._apply_button_mapping("VOLUME_UP", mapping)
        assert off_activity.volume_up_command == mapping

    def test_apply_button_mapping_play_pause(self, off_activity: Activity):
        mapping = {"cmd_id": "media_player.play_pause", "entity_id": "media_player.tv"}
        off_activity._apply_button_mapping(
            "PLAY", mapping
        )  # API uses "PLAY" for the play/pause button
        assert off_activity.play_pause_command == mapping

    def test_apply_button_mapping_unknown_button(self, off_activity: Activity):
        # Should not raise for unknown buttons
        off_activity._apply_button_mapping("UNKNOWN_BUTTON", {"cmd_id": "something"})

    def test_apply_none_mapping_is_ignored(self, off_activity: Activity):
        off_activity._apply_button_mapping("VOLUME_UP", None)
        assert off_activity.volume_up_command is None


class TestActivityTurnOn:
    async def test_turn_on_calls_api(self, on_activity: Activity, remote: Remote):
        on_activity._set_state("OFF")
        with aioresponses() as m:
            m.put(
                f"{BASE_URL}entities/act-001/command",
                payload={"status": "ok"},
            )
            await on_activity.turn_on()

    async def test_turn_off_calls_api(self, on_activity: Activity):
        with aioresponses() as m:
            m.put(
                f"{BASE_URL}entities/act-001/command",
                payload={"status": "ok"},
            )
            await on_activity.turn_off()


class TestActivityMediaPlayers:
    def test_add_media_player_entity(self, off_activity: Activity):
        from unfurled.entities.media_player import MediaPlayerEntity

        mp = MediaPlayerEntity("media_player.tv", off_activity._remote)
        off_activity.add_media_player_entity(mp)
        assert len(off_activity.media_player_entities) == 1

    def test_add_same_entity_twice_does_not_duplicate(self, off_activity: Activity):
        from unfurled.entities.media_player import MediaPlayerEntity

        mp = MediaPlayerEntity("media_player.tv", off_activity._remote)
        off_activity.add_media_player_entity(mp)
        off_activity.add_media_player_entity(mp)
        assert len(off_activity.media_player_entities) == 1


class TestActivityRefresh:
    async def test_refresh_updates_state(self, off_activity: Activity):
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}activities/act-002",
                payload={"entity_id": "act-002", "attributes": {"state": "ON"}, "options": {}},
            )
            await off_activity.refresh()
        assert off_activity.state == ActivityState.ON


class TestActivityGroup:
    @pytest.fixture
    def group(self, remote: Remote, on_activity: Activity, off_activity: Activity):
        g = ActivityGroup(
            group_id="grp-001",
            name="Living Room",
            remote=remote,
            state="OFF",
        )
        g.activities = [on_activity, off_activity]
        return g

    def test_group_name(self, group: ActivityGroup):
        assert group.name == "Living Room"

    def test_contains_returns_true_for_member(self, group: ActivityGroup):
        assert group.contains("act-001")

    def test_contains_returns_false_for_non_member(self, group: ActivityGroup):
        assert not group.contains("act-999")

    def test_recalculate_state_on_when_any_on(self, group: ActivityGroup):
        group._recalculate_state()
        assert group.state == ActivityState.ON

    def test_recalculate_state_off_when_all_off(self, group: ActivityGroup, off_activity: Activity):
        for act in group.activities:
            act._set_state("OFF")
        group._recalculate_state()
        assert group.state == ActivityState.OFF

    async def test_refresh_fetches_each_activity(self, group: ActivityGroup):
        with aioresponses() as m:
            for act in group.activities:
                m.get(
                    f"{BASE_URL}activities/{act.id}",
                    payload={"entity_id": act.id, "attributes": {"state": "OFF"}, "options": {}},
                )
            await group.refresh()
