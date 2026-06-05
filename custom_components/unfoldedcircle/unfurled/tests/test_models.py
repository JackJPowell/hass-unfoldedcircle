"""Tests for the WebSocket message parser (models.py)."""

from __future__ import annotations

import json

from unfurled.helpers.models import (
    ActivityEntityLinkEvent,
    ActivityStateEvent,
    AmbientLightEvent,
    BatteryEvent,
    ConfigurationChangeEvent,
    IRLearningEvent,
    MediaPlayerAttributesEvent,
    PowerModeEvent,
    SoftwareUpdateEvent,
    parse_ws_message,
)


class TestBatteryMessage:
    def test_parses_battery_status(self):
        raw = json.dumps(
            {
                "msg": "battery_status",
                "msg_data": {"capacity": 72, "status": "DISCHARGING", "power_supply": False},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, BatteryEvent)
        assert event.capacity == 72
        assert event.status == "DISCHARGING"
        assert event.power_supply is False

    def test_parses_charging_battery(self):
        raw = json.dumps(
            {
                "msg": "battery_status",
                "msg_data": {"capacity": 90, "status": "CHARGING", "power_supply": True},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, BatteryEvent)
        assert event.power_supply is True


class TestAmbientLightMessage:
    def test_parses_ambient_light(self):
        raw = json.dumps(
            {
                "msg": "ambient_light",
                "msg_data": {"intensity": 250},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, AmbientLightEvent)
        assert event.intensity == 250


class TestIRLearningMessage:
    def test_parses_ir_learning(self):
        raw = json.dumps(
            {
                "msg": "ir_learning",
                "msg_data": {
                    "device_id": "emitter-001",
                    "code": {"format": "HEX", "data": "0xABCD"},
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, IRLearningEvent)
        assert event.device_id == "emitter-001"
        assert event.code["format"] == "HEX"


class TestSoftwareUpdateMessage:
    def test_parses_update_start(self):
        raw = json.dumps(
            {
                "msg": "software_update",
                "msg_data": {"event_type": "START"},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, SoftwareUpdateEvent)
        assert event.event_type == "START"

    def test_parses_update_progress(self):
        raw = json.dumps(
            {
                "msg": "software_update",
                "msg_data": {
                    "event_type": "PROGRESS",
                    "progress": {
                        "state": "RUN",
                        "current_step": 1,
                        "total_steps": 2,
                        "current_percent": 50,
                    },
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, SoftwareUpdateEvent)
        assert event.progress["state"] == "RUN"


class TestConfigurationChangeMessage:
    def test_parses_display_change(self):
        raw = json.dumps(
            {
                "msg": "configuration_change",
                "msg_data": {"new_state": {"display": {"auto_brightness": True, "brightness": 80}}},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ConfigurationChangeEvent)
        assert event.new_state["display"]["brightness"] == 80

    def test_parses_network_change(self):
        raw = json.dumps(
            {
                "msg": "configuration_change",
                "msg_data": {"new_state": {"network": {"wake_on_wlan": {"enabled": True}}}},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ConfigurationChangeEvent)
        assert event.new_state["network"]["wake_on_wlan"]["enabled"] is True


class TestPowerModeMessage:
    def test_parses_power_mode(self):
        raw = json.dumps(
            {
                "msg": "power_mode_change",
                "msg_data": {"mode": "SUSPEND"},
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, PowerModeEvent)
        assert event.mode == "SUSPEND"


class TestActivityStateMessages:
    def test_activity_on(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "activity",
                    "entity_id": "act-001",
                    "new_state": {"attributes": {"state": "ON"}},
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ActivityStateEvent)
        assert event.entity_id == "act-001"
        assert event.state == "ON"

    def test_activity_off(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "activity",
                    "entity_id": "act-002",
                    "new_state": {"attributes": {"state": "OFF"}},
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ActivityStateEvent)
        assert event.state == "OFF"

    def test_activity_on_with_included_entities(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "activity",
                    "entity_id": "act-001",
                    "new_state": {
                        "attributes": {"state": "ON"},
                        "options": {
                            "included_entities": [
                                {"entity_id": "media_player.tv", "entity_type": "media_player"}
                            ]
                        },
                    },
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ActivityStateEvent)
        assert len(event.included_entities) == 1

    def test_activity_running_yields_entity_link(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "activity",
                    "entity_id": "act-001",
                    "new_state": {
                        "attributes": {
                            "state": "RUNNING",
                            "step": {
                                "entity": {"type": "media_player"},
                                "command": {
                                    "cmd_id": "media_player.on",
                                    "entity_id": "media_player.tv",
                                },
                            },
                        }
                    },
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, ActivityEntityLinkEvent)
        assert event.activity_id == "act-001"
        assert event.entity_id == "media_player.tv"

    def test_activity_running_non_mp_step_returns_none(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "activity",
                    "entity_id": "act-001",
                    "new_state": {
                        "attributes": {
                            "state": "RUNNING",
                            "step": {
                                "entity": {"type": "button"},
                                "command": {"cmd_id": "button.on", "entity_id": "button.1"},
                            },
                        }
                    },
                },
            }
        )
        event = parse_ws_message(raw)
        # RUNNING but not a media_player.on → None
        assert event is None


class TestMediaPlayerMessage:
    def test_parses_media_player_attributes(self):
        raw = json.dumps(
            {
                "msg": "entity_change",
                "msg_data": {
                    "entity_type": "media_player",
                    "entity_id": "media_player.tv",
                    "new_state": {
                        "attributes": {
                            "state": "PLAYING",
                            "volume": 45,
                            "media_title": "Test Movie",
                        }
                    },
                },
            }
        )
        event = parse_ws_message(raw)
        assert isinstance(event, MediaPlayerAttributesEvent)
        assert event.entity_id == "media_player.tv"
        assert event.attributes["state"] == "PLAYING"
        assert event.attributes["volume"] == 45


class TestInvalidMessages:
    def test_returns_none_for_invalid_json(self):
        assert parse_ws_message("not json") is None

    def test_returns_none_for_unknown_message_type(self):
        raw = json.dumps({"msg": "unknown_event", "msg_data": {}})
        assert parse_ws_message(raw) is None

    def test_returns_none_for_empty_string(self):
        assert parse_ws_message("") is None

    def test_returns_none_for_ack_frame(self):
        raw = json.dumps({"kind": "resp", "id": 1, "code": 200})
        assert parse_ws_message(raw) is None
