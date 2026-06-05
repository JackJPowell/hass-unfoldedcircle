"""Tests for the helpers module: Helpers class, exceptions, models, and discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from unfurled.helpers.discovery import DiscoveredDevice
from unfurled.helpers.exceptions import (
    ApiKeyNotFound,
    AuthenticationError,
    DockNotFound,
    EntityCommandError,
    HTTPError,
    IntegrationNotFound,
    InvalidButtonCommand,
    InvalidIRFormat,
    NoActivityRunning,
    NoEmitterFound,
    RemoteIsSleeping,
    SystemCommandNotFound,
    UnfurledError,
)
from unfurled.helpers.helpers import Helpers
from unfurled.helpers.models import (
    DeviceInfo,
    RemoteState,
    RemoteStats,
)

# ---------------------------------------------------------------------------
# Helpers: test fixture
# ---------------------------------------------------------------------------


def make_helpers() -> Helpers:
    """Return a Helpers instance backed by a mock Remote with a mock CoreAPI."""
    mock_remote = MagicMock()
    mock_api = MagicMock()
    mock_remote.api = mock_api
    helpers = Helpers(mock_remote)
    return helpers, mock_api


# ---------------------------------------------------------------------------
# Helpers.find_orphaned_entities
# ---------------------------------------------------------------------------


class TestFindOrphanedEntities:
    async def test_returns_empty_when_no_orphans(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [
                        {
                            "entity_id": "media_player.tv",
                            "entity_type": "media_player",
                            "available": True,
                        }
                    ]
                },
            }
        )

        result = await helpers.find_orphaned_entities()

        assert result == []

    async def test_finds_unavailable_entity(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [
                        {
                            "entity_id": "media_player.deleted",
                            "entity_type": "media_player",
                            "available": False,
                            "entity_commands": ["on", "off"],
                            "simple_commands": ["play"],
                        }
                    ]
                },
            }
        )

        result = await helpers.find_orphaned_entities()

        assert len(result) == 1
        assert result[0]["entity_id"] == "media_player.deleted"
        assert result[0]["activity_id"] == "act-001"
        assert "entity_commands" not in result[0]
        assert "simple_commands" not in result[0]

    async def test_skips_available_entity(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [
                        {"entity_id": "media_player.good", "entity_type": "media_player"},
                        {"entity_id": "media_player.bad", "available": False},
                    ]
                },
            }
        )

        result = await helpers.find_orphaned_entities()

        assert len(result) == 1
        assert result[0]["entity_id"] == "media_player.bad"

    async def test_skips_activity_with_no_entity_id(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"name": {"en": "No ID"}}]  # no entity_id key
        )

        result = await helpers.find_orphaned_entities()

        assert result == []
        mock_api.get_activity.assert_not_called()

    async def test_returns_empty_on_network_error(self):
        helpers, mock_api = make_helpers()
        import aiohttp

        mock_api.get_activities = AsyncMock(side_effect=aiohttp.ClientError("timeout"))

        result = await helpers.find_orphaned_entities()

        assert result == []

    async def test_includes_activity_name_in_result(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [
                        {"entity_id": "mp.gone", "available": False},
                    ]
                },
            }
        )

        result = await helpers.find_orphaned_entities()

        assert result[0]["activity_name"] == {"en": "Watch TV"}


# ---------------------------------------------------------------------------
# Helpers._extract_used_entity_ids
# ---------------------------------------------------------------------------


class TestExtractUsedEntityIds:
    def test_empty_activity(self):
        helpers, _ = make_helpers()
        assert helpers._extract_used_entity_ids({}) == set()

    def test_extracts_from_sequences(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "sequences": {
                    "on": [
                        {"command": {"entity_id": "media_player.tv"}},
                        {"command": {"entity_id": "media_player.amp"}},
                    ]
                }
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert used == {"media_player.tv", "media_player.amp"}

    def test_extracts_from_button_mapping(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "button_mapping": [
                    {
                        "short_press": {"entity_id": "media_player.tv"},
                        "long_press": {"entity_id": "media_player.amp"},
                    }
                ]
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert used == {"media_player.tv", "media_player.amp"}

    def test_extracts_media_player_id_from_ui(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "user_interface": {"pages": [{"items": [{"media_player_id": "media_player.tv"}]}]}
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert "media_player.tv" in used

    def test_extracts_sensor_id_from_ui(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "user_interface": {"pages": [{"items": [{"sensor": {"sensor_id": "sensor.temp"}}]}]}
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert "sensor.temp" in used

    def test_extracts_select_id_from_ui(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "user_interface": {
                    "pages": [{"items": [{"select": {"select_id": "select.source"}}]}]
                }
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert "select.source" in used

    def test_extracts_command_entity_from_ui(self):
        helpers, _ = make_helpers()
        activity = {
            "options": {
                "user_interface": {"pages": [{"items": [{"command": {"entity_id": "remote.tv"}}]}]}
            }
        }
        used = helpers._extract_used_entity_ids(activity)
        assert "remote.tv" in used

    def test_ignores_non_list_sequences(self):
        helpers, _ = make_helpers()
        activity = {"options": {"sequences": {"on": "not-a-list"}}}
        # Should not raise
        used = helpers._extract_used_entity_ids(activity)
        assert used == set()


# ---------------------------------------------------------------------------
# Helpers.find_unused_activity_entities
# ---------------------------------------------------------------------------


class TestFindUnusedActivityEntities:
    async def test_returns_empty_when_all_used(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [{"entity_id": "media_player.tv"}],
                    "sequences": {"on": [{"command": {"entity_id": "media_player.tv"}}]},
                },
            }
        )

        result = await helpers.find_unused_activity_entities()

        assert result == []

    async def test_finds_unused_entity(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Watch TV"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={
                "entity_id": "act-001",
                "options": {
                    "included_entities": [
                        {"entity_id": "media_player.tv"},
                        {"entity_id": "media_player.unused", "entity_commands": ["on"]},
                    ],
                    "sequences": {"on": [{"command": {"entity_id": "media_player.tv"}}]},
                },
            }
        )

        result = await helpers.find_unused_activity_entities()

        assert len(result) == 1
        assert result[0]["entity_id"] == "media_player.unused"
        assert "entity_commands" not in result[0]
        assert result[0]["activity_id"] == "act-001"

    async def test_skips_activity_with_no_included_entities(self):
        helpers, mock_api = make_helpers()
        mock_api.get_activities = AsyncMock(
            return_value=[{"entity_id": "act-001", "name": {"en": "Empty"}}]
        )
        mock_api.get_activity = AsyncMock(
            return_value={"entity_id": "act-001", "options": {"included_entities": []}}
        )

        result = await helpers.find_unused_activity_entities()

        assert result == []

    async def test_returns_empty_on_network_error(self):
        helpers, mock_api = make_helpers()
        import aiohttp

        mock_api.get_activities = AsyncMock(side_effect=aiohttp.ClientError("timeout"))

        result = await helpers.find_unused_activity_entities()

        assert result == []


# ---------------------------------------------------------------------------
# DeviceInfo properties
# ---------------------------------------------------------------------------


class TestDeviceInfo:
    def test_model_name_from_ucr2(self):
        d = DeviceInfo(model_number="UCR2")
        assert d.model_name == "Remote Two"

    def test_model_name_from_ucr3(self):
        d = DeviceInfo(model_number="UCR3")
        assert d.model_name == "Remote 3"

    def test_model_name_passthrough(self):
        d = DeviceInfo()
        d.model_name = "Custom Remote"
        assert d.model_name == "Custom Remote"

    def test_model_name_unknown_number(self):
        d = DeviceInfo(model_number="UCR9")
        assert d.model_name == ""

    def test_hw_revision_rev2(self):
        d = DeviceInfo()
        d.hw_revision = "rev2"
        assert d.hw_revision == "Revision 2"

    def test_hw_revision_rev3(self):
        d = DeviceInfo()
        d.hw_revision = "rev3"
        assert d.hw_revision == "Revision 3"

    def test_hw_revision_passthrough(self):
        d = DeviceInfo()
        d.hw_revision = "rev99"
        assert d.hw_revision == "rev99"

    def test_name_default_fallback(self):
        d = DeviceInfo()
        assert d.name == "Unfolded Circle Remote"

    def test_name_set(self):
        d = DeviceInfo()
        d.name = "Living Room"
        assert d.name == "Living Room"

    def test_sw_version_default(self):
        d = DeviceInfo()
        assert d.sw_version == "N/A"

    def test_sw_version_set(self):
        d = DeviceInfo()
        d.sw_version = "2.3.0"
        assert d.sw_version == "2.3.0"


# ---------------------------------------------------------------------------
# RemoteStats properties
# ---------------------------------------------------------------------------


class TestRemoteStats:
    def test_memory_available_rounds(self):
        s = RemoteStats()
        s.memory_available = 204_800_000.9
        assert s.memory_available == 204_800_001

    def test_storage_available_rounds(self):
        s = RemoteStats()
        s.storage_available = 9_000_000.1
        assert s.storage_available == 9_000_000

    def test_memory_total_rounds(self):
        s = RemoteStats()
        s.memory_total = 512_000_000.6
        assert s.memory_total == 512_000_001

    def test_storage_total_rounds(self):
        s = RemoteStats()
        s.storage_total = 10_000_000.4
        assert s.storage_total == 10_000_000

    def test_defaults_are_zero(self):
        s = RemoteStats()
        assert s.memory_available == 0
        assert s.storage_available == 0


# ---------------------------------------------------------------------------
# RemoteState defaults
# ---------------------------------------------------------------------------


class TestRemoteState:
    def test_defaults(self):
        s = RemoteState()
        assert s.battery_level == 0
        assert s.battery_status == ""
        assert s.is_charging is False
        assert s.ambient_light_level == 0
        assert s.online is True

    def test_mutation(self):
        s = RemoteState()
        s.battery_level = 75
        s.battery_status = "DISCHARGING"
        assert s.battery_level == 75
        assert s.battery_status == "DISCHARGING"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_unfurled_error_is_exception(self):
        err = UnfurledError("base error")
        assert isinstance(err, Exception)

    def test_http_error_attributes(self):
        err = HTTPError(404, "Not found")
        assert err.status_code == 404
        assert err.message == "Not found"
        assert "404" in str(err)

    def test_remote_is_sleeping_message(self):
        err = RemoteIsSleeping()
        assert "sleeping" in str(err).lower()

    def test_no_activity_running_message(self):
        err = NoActivityRunning()
        assert "No activities" in str(err)

    def test_system_command_not_found(self):
        err = SystemCommandNotFound("INVALID_CMD")
        assert err.command == "INVALID_CMD"
        assert "INVALID_CMD" in str(err)

    def test_api_key_not_found(self):
        err = ApiKeyNotFound("myKey")
        assert err.name == "myKey"
        assert "myKey" in str(err)

    def test_authentication_error(self):
        err = AuthenticationError("bad key")
        assert isinstance(err, UnfurledError)

    def test_dock_not_found(self):
        err = DockNotFound("no dock")
        assert isinstance(err, UnfurledError)

    def test_integration_not_found(self):
        err = IntegrationNotFound("no integration")
        assert isinstance(err, UnfurledError)

    def test_invalid_button_command(self):
        err = InvalidButtonCommand("bad button")
        assert isinstance(err, UnfurledError)

    def test_entity_command_error(self):
        err = EntityCommandError("failed")
        assert isinstance(err, UnfurledError)

    def test_invalid_ir_format(self):
        err = InvalidIRFormat("bad format")
        assert isinstance(err, UnfurledError)

    def test_no_emitter_found(self):
        err = NoEmitterFound("no emitter")
        assert isinstance(err, UnfurledError)


# ---------------------------------------------------------------------------
# DiscoveredDevice
# ---------------------------------------------------------------------------


class TestDiscoveredDevice:
    def test_api_url_construction(self):
        device = DiscoveredDevice(name="Remote Two", host="192.168.1.10", port=80)
        assert device.api_url == "http://192.168.1.10:80/api/"

    def test_api_url_non_default_port(self):
        device = DiscoveredDevice(name="Remote Two", host="10.0.0.5", port=8080)
        assert device.api_url == "http://10.0.0.5:8080/api/"

    def test_properties_default(self):
        device = DiscoveredDevice(name="Remote Two", host="192.168.1.1", port=80)
        assert device.properties == {}

    def test_properties_populated(self):
        device = DiscoveredDevice(
            name="Remote Two",
            host="192.168.1.1",
            port=80,
            properties={"model": "UCR2"},
        )
        assert device.properties["model"] == "UCR2"
