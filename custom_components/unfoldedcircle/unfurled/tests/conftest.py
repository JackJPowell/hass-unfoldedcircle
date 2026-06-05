"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import json

import pytest

from unfurled import Remote

BASE_URL = "http://192.168.1.10/api/"
API_KEY = "test-api-key"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def make_system_info() -> dict:
    return {
        "model_name": "Remote Two",
        "model_number": "UCR2",
        "serial_number": "UC-R2-001",
        "hw_revision": "rev2",
    }


def make_version_info() -> dict:
    return {
        "hostname": "remote-two",
        "address": "aa:bb:cc:dd:ee:ff",
        "os": "2.3.0",
    }


def make_wifi_info() -> dict:
    return {
        "address": "aa:bb:cc:dd:ee:ff",
        "ip_address": "192.168.1.10",
    }


def make_configuration() -> dict:
    return {
        "device": {"name": "Living Room Remote"},
        "display": {"auto_brightness": False, "brightness": 60},
        "button": {"auto_brightness": True, "brightness": 80, "static_color": None},
        "sound": {"enabled": True, "volume": 50},
        "haptic": {"enabled": True},
        "power_saving": {"display_off_sec": 30, "wakeup_sensitivity": 2, "standby_sec": 900},
        "network": {
            "bt_enabled": True,
            "wifi_enabled": True,
            "wifi": {
                "wake_on_wlan": {"enabled": False},
                "band": "auto",
                "scan_interval_sec": 15,
                "ipv4_type": "DHCP",
            },
            "bt": {"address": "AA:BB:CC:DD:EE:FF"},
        },
        "software_update": {
            "check_for_updates": True,
            "auto_update": False,
            "ota_window_start": "02:00:00",
            "ota_window_end": "05:00:00",
            "channel": "STABLE",
        },
        "localization": {
            "language_code": "en_US",
            "country_code": "US",
            "time_zone": "UTC",
            "time_format_24h": True,
            "measurement_unit": "METRIC",
        },
        "bt": {
            "peripheral_connections": 1,
            "advertisement_name": "Remote Two",
            "enable_hci_log": False,
            "enable_debug_port": False,
            "version": "5.1",
        },
        "profile": {"has_admin_pin": False},
        "voice": {"microphone": False, "voice_assistant": {}},
        "features": [
            {"id": "internal_ir", "enabled": True, "title": {}, "description": {}, "help_url": ""},
            {
                "id": "multiple_bt_peripherals",
                "enabled": False,
                "title": {},
                "description": {},
                "help_url": "",
            },
        ],
    }


def make_battery() -> dict:
    return {"capacity": 85, "status": "DISCHARGING", "power_supply": False}


def make_display_settings() -> dict:
    return {"auto_brightness": False, "brightness": 60}


def make_button_settings() -> dict:
    return {"auto_brightness": True, "brightness": 80, "static_color": None}


def make_sound_settings() -> dict:
    return {"enabled": True, "volume": 50}


def make_haptic_settings() -> dict:
    return {"enabled": True}


def make_power_saving_settings() -> dict:
    return {"display_off_sec": 30, "wakeup_sensitivity": 2, "standby_sec": 900}


def make_network_settings() -> dict:
    return {
        "bt_enabled": True,
        "wifi_enabled": True,
        "wake_on_wlan": {"enabled": False, "available": True},
    }


def make_localization() -> dict:
    return {
        "language_code": "en_UK",
        "country_code": "GB",
        "time_zone": "UTC",
        "time_format_24h": True,
        "measurement_unit": "UK",
    }


def make_activities() -> list[dict]:
    return [
        {
            "entity_id": "act-001",
            "name": {"en": "Watch TV"},
            "attributes": {"state": "OFF"},
        },
        {
            "entity_id": "act-002",
            "name": {"en": "Listen to Music"},
            "attributes": {"state": "ON"},
        },
    ]


def make_activity_detail(activity_id: str) -> dict:
    return {
        "entity_id": activity_id,
        "options": {
            "included_entities": [
                {
                    "entity_id": "media_player.tv",
                    "entity_type": "media_player",
                    "name": {"en": "TV"},
                    "entity_commands": ["media_player.on", "media_player.off"],
                }
            ]
        },
        "attributes": {"state": "OFF"},
    }


def make_ir_emitters() -> list[dict]:
    return [
        {"device_id": "emitter-001", "name": "Internal IR", "type": "internal", "state": "ACTIVE"},
        {"device_id": "emitter-002", "name": "Dock IR", "type": "dock", "state": "ACTIVE"},
    ]


def make_docks() -> list[dict]:
    return [
        {
            "entity_id": "uc-dock-aa:bb:cc:dd:ee:01",
            "name": "Living Room Dock",
            "ws_url": "ws://192.168.1.20:8080/ws",
            "active": True,
            "model_number": "UCD2",
            "hardware_revision": "rev1",
            "serial_number": "UCD2-001",
            "led_brightness": 50,
            "ethernet_led_brightness": 50,
            "software_version": "1.0.0",
            "state": "CONNECTED",
        }
    ]


# ---------------------------------------------------------------------------
# WS message builders
# ---------------------------------------------------------------------------


def ws_battery_message(
    capacity: int = 75, status: str = "DISCHARGING", power_supply: bool = False
) -> str:
    return json.dumps(
        {
            "msg": "battery_status",
            "msg_data": {"capacity": capacity, "status": status, "power_supply": power_supply},
        }
    )


def ws_ambient_light_message(intensity: int = 100) -> str:
    return json.dumps(
        {
            "msg": "ambient_light",
            "msg_data": {"intensity": intensity},
        }
    )


def ws_activity_on_message(entity_id: str = "act-001", state: str = "ON") -> str:
    return json.dumps(
        {
            "msg": "entity_change",
            "msg_data": {
                "entity_type": "activity",
                "entity_id": entity_id,
                "new_state": {"attributes": {"state": state}},
            },
        }
    )


def ws_activity_off_message(entity_id: str = "act-001") -> str:
    return ws_activity_on_message(entity_id, "OFF")


def ws_configuration_change_message(display_brightness: int = 75) -> str:
    return json.dumps(
        {
            "msg": "configuration_change",
            "msg_data": {
                "new_state": {
                    "display": {"auto_brightness": False, "brightness": display_brightness},
                }
            },
        }
    )


def ws_power_mode_message(mode: str = "SUSPEND") -> str:
    return json.dumps(
        {
            "msg": "power_mode_change",
            "msg_data": {"mode": mode},
        }
    )


def ws_software_update_start() -> str:
    return json.dumps(
        {
            "msg": "software_update",
            "msg_data": {"event_type": "START"},
        }
    )


def ws_software_update_progress(state: str = "PROGRESS", current_percent: int = 50) -> str:
    return json.dumps(
        {
            "msg": "software_update",
            "msg_data": {
                "event_type": "PROGRESS",
                "progress": {
                    "state": state,
                    "current_step": 1,
                    "total_steps": 1,
                    "current_percent": current_percent,
                },
            },
        }
    )


def ws_ir_learning_message(device_id: str = "emitter-001") -> str:
    return json.dumps(
        {
            "msg": "ir_learning",
            "msg_data": {
                "device_id": device_id,
                "code": {"format": "HEX", "data": "0x1234"},
            },
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key() -> str:
    return API_KEY


@pytest.fixture
def base_url() -> str:
    return BASE_URL


@pytest.fixture
async def remote(base_url: str, api_key: str) -> Remote:
    """Return a freshly created Remote (not initialised), cleaned up after test."""
    r = Remote(base_url, api_key=api_key)
    yield r
    await r.close()
