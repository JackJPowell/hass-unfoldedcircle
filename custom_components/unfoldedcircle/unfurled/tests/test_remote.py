"""Tests for the Remote class: initialization, WS dispatch, and helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses

from unfurled import Remote
from unfurled.helpers.exceptions import RemoteIsSleeping, SystemCommandNotFound
from unfurled.helpers.models import UpdateType

from .conftest import (
    API_KEY,
    BASE_URL,
    make_activities,
    make_activity_detail,
    make_battery,
    make_configuration,
    make_docks,
    make_ir_emitters,
    make_system_info,
    make_version_info,
    make_wifi_info,
    ws_activity_off_message,
    ws_activity_on_message,
    ws_ambient_light_message,
    ws_battery_message,
    ws_configuration_change_message,
    ws_ir_learning_message,
    ws_power_mode_message,
    ws_software_update_progress,
    ws_software_update_start,
)


def setup_default_api_mocks(m: aioresponses, base: str = BASE_URL) -> None:
    """Register the most common GET responses needed for Remote.init()."""
    m.get(f"{base}pub/version", payload=make_version_info())
    m.get(f"{base}system", payload=make_system_info())
    m.get(f"{base}system/wifi", payload=make_wifi_info())
    m.get(f"{base}cfg", payload=make_configuration())
    m.get(f"{base}system/power/battery", payload=make_battery())
    m.get(f"{base}system/power", payload={"mode": "NORMAL"})
    m.get(
        f"{base}system/power/charger",
        payload={"features": [], "wireless_charging": False, "wireless_charging_enabled": False},
    )
    m.get(f"{base}system/sensors/ambient_light", payload={"intensity": 120})
    m.get(
        f"{base}pub/status",
        payload={
            "memory": {"total_memory": 512_000_000, "available_memory": 200_000_000},
            "filesystem": {"user_data": {"used": 1_000_000, "available": 9_000_000}},
            "load_avg": {"one": 0.5},
        },
    )
    m.get(
        f"{base}system/update",
        payload={
            "version": "2.4.0",
            "release_notes_url": "",
            "release_notes": "",
            "next_check_date": "",
            "updates": [],
        },
    )
    m.get(f"{base}ir/emitters?limit=100", payload=make_ir_emitters())
    m.get(f"{base}activities?limit=100", payload=make_activities())
    m.get(f"{base}activities/act-001", payload=make_activity_detail("act-001"))
    m.get(f"{base}activities/act-002", payload=make_activity_detail("act-002"))
    m.get(f"{base}activities/act-001/buttons", payload=[])
    m.get(f"{base}activities/act-002/buttons", payload=[])
    m.get(f"{base}docks?limit=100", payload=make_docks())
    m.get(f"{base}remotes", payload=[])
    m.get(f"{base}activities/groups", payload=[])


class TestRemoteUrlNormalization:
    def test_adds_scheme(self):
        r = Remote("192.168.1.10")
        assert r.endpoint.startswith("http://")

    def test_adds_api_path(self):
        r = Remote("http://192.168.1.10")
        assert r.endpoint == "http://192.168.1.10/api/"

    def test_preserves_full_url(self):
        r = Remote("http://192.168.1.10/api/")
        assert r.endpoint == "http://192.168.1.10/api/"

    def test_derives_config_url(self):
        r = Remote("http://192.168.1.10/api/")
        assert r.configuration_url == "http://192.168.1.10/configurator/"


class TestRemoteInit:
    async def test_init_populates_basic_info(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert remote.device.hostname == "remote-two"
        assert remote.device.mac_address == "aa:bb:cc:dd:ee:ff"
        assert remote.device.sw_version == "2.3.0"

    async def test_init_populates_battery(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert remote.state.battery_level == 85
        assert remote.state.battery_status == "DISCHARGING"
        assert remote.state.is_charging is False

    async def test_init_populates_settings(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert remote.settings.display.brightness == 60
        assert remote.settings.sound.enabled is True
        assert remote.settings.haptic.enabled is True
        assert remote.settings.power_saving.display_off_sec == 30

    async def test_init_populates_activities(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert len(remote.activities) == 2
        assert remote.activities[0].id == "act-001"

    async def test_init_populates_ir_emitters(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert len(remote.ir_emitters) == 2
        assert remote.ir_emitters[0].name == "Internal IR"

    async def test_init_populates_docks(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert len(remote.docks) == 1
        assert remote.docks[0].device.name == "Living Room Dock"

    async def test_init_detects_system_name(self, remote: Remote):
        with aioresponses() as m:
            setup_default_api_mocks(m)
            await remote.init()

        assert remote.device.name == "Living Room Remote"


class TestWsMessageHandling:
    async def test_battery_message_updates_state(self, remote: Remote):
        await remote._handle_ws_message(
            ws_battery_message(capacity=55, status="CHARGING", power_supply=True)
        )
        assert remote.state.battery_level == 55
        assert remote.state.battery_status == "CHARGING"
        assert remote.state.is_charging is True
        assert remote._last_update_type == UpdateType.BATTERY

    async def test_ambient_light_updates_state(self, remote: Remote):
        await remote._handle_ws_message(ws_ambient_light_message(intensity=300))
        assert remote.state.ambient_light_level == 300
        assert remote._last_update_type == UpdateType.AMBIENT_LIGHT

    async def test_activity_on_message_updates_activity_state(self, remote: Remote):
        from unfurled.entities.activity import Activity

        act = Activity(
            {"entity_id": "act-001", "name": {"en": "Watch TV"}, "attributes": {"state": "OFF"}},
            remote,
        )
        remote.activities.append(act)

        await remote._handle_ws_message(ws_activity_on_message("act-001", "ON"))
        assert remote.activities[0].is_on is True
        assert remote._last_update_type == UpdateType.ACTIVITY

    async def test_activity_off_message_updates_activity_state(self, remote: Remote):
        from unfurled.entities.activity import Activity

        act = Activity(
            {"entity_id": "act-001", "name": {"en": "Watch TV"}, "attributes": {"state": "ON"}},
            remote,
        )
        remote.activities.append(act)

        await remote._handle_ws_message(ws_activity_off_message("act-001"))
        assert remote.activities[0].is_on is False

    async def test_configuration_change_updates_display_brightness(self, remote: Remote):
        await remote._handle_ws_message(ws_configuration_change_message(display_brightness=75))
        assert remote.settings.display.brightness == 75
        assert remote._last_update_type == UpdateType.CONFIGURATION

    async def test_power_mode_message_updates_mode(self, remote: Remote):
        await remote._handle_ws_message(ws_power_mode_message("SUSPEND"))
        assert remote.state.power_mode == "SUSPEND"

    async def test_software_update_start_sets_in_progress(self, remote: Remote):
        await remote._handle_ws_message(ws_software_update_start())
        assert remote.system.update_info.in_progress is True
        assert remote._last_update_type == UpdateType.SOFTWARE

    async def test_software_update_progress(self, remote: Remote):
        await remote._handle_ws_message(ws_software_update_progress("PROGRESS", current_percent=70))
        assert remote.system.update_info.update_percent == 70

    async def test_ir_learning_routes_to_dock(self, remote: Remote):
        from unfurled.dock import Dock

        dock_data = {
            "entity_id": "emitter-001",
            "name": "Dock",
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
        dock = Dock.from_dict(
            dock_data, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        remote.docks.append(dock)

        await remote._handle_ws_message(ws_ir_learning_message("emitter-001"))
        assert dock._learned_code is not None

    async def test_invalid_json_is_silently_ignored(self, remote: Remote):
        await remote._handle_ws_message("not json at all")  # should not raise

    async def test_unknown_message_type_is_ignored(self, remote: Remote):
        raw = json.dumps({"msg": "unsupported_msg", "msg_data": {}})
        await remote._handle_ws_message(raw)  # should not raise


class TestSystemCommands:
    async def test_valid_system_command_sent(self, remote: Remote):
        remote._wake_if_asleep = False
        with aioresponses() as m:
            m.post(f"{BASE_URL}system?cmd=STANDBY", status=200, payload=None)
            await remote.system.send_command("STANDBY")

    async def test_invalid_system_command_raises(self, remote: Remote):
        with pytest.raises(SystemCommandNotFound):
            await remote.system.send_command("INVALID_CMD")


class TestGetTextForLocale:
    def test_returns_exact_locale_match(self, remote: Remote):
        text = {"en_UK": "Hello UK", "en_US": "Hello US"}
        assert remote.settings.get_text_for_locale(text) == "Hello US"

    def test_falls_back_to_language_code(self, remote: Remote):
        text = {"en": "Hello"}
        assert remote.settings.get_text_for_locale(text) == "Hello"

    def test_returns_default_for_empty_dict(self, remote: Remote):
        assert remote.settings.get_text_for_locale({}, default_text="Default") == "Default"

    def test_returns_string_directly(self, remote: Remote):
        assert remote.settings.get_text_for_locale("Plain text") == "Plain text"

    def test_returns_default_for_none(self, remote: Remote):
        assert remote.settings.get_text_for_locale(None, default_text="Fallback") == "Fallback"


class TestWakeOnLan:
    async def test_wake_if_asleep_with_wol_enabled(self, remote: Remote):
        remote._wake_if_asleep = True
        remote.settings.network.wifi.wake_on_wlan = True
        remote.device.is_simulator = False

        with patch.object(remote, "wake", new=AsyncMock(return_value=True)):
            await remote._ensure_awake()  # Should not raise

    async def test_ensure_awake_raises_when_wake_fails(self, remote: Remote):
        remote._wake_if_asleep = True
        remote.settings.network.wifi.wake_on_wlan = True
        remote.device.is_simulator = False

        with patch.object(remote, "wake", new=AsyncMock(return_value=False)):  # noqa: SIM117
            with pytest.raises(RemoteIsSleeping):
                await remote._ensure_awake()

    async def test_ensure_awake_no_op_when_wol_disabled(self, remote: Remote):
        remote._wake_if_asleep = True
        remote.settings.network.wifi.wake_on_wlan = False

        # Should complete without calling wake
        await remote._ensure_awake()


class TestGetActiveActivities:
    async def test_returns_on_activities(self, remote: Remote):
        from unfurled.entities.activity import Activity

        act1 = Activity({"entity_id": "a1", "name": {}, "attributes": {"state": "ON"}}, remote)
        act2 = Activity({"entity_id": "a2", "name": {}, "attributes": {"state": "OFF"}}, remote)
        remote.activities = [act1, act2]

        # Patch _fetch_activities_state to be a no-op
        with patch.object(remote, "_fetch_activities_state", new=AsyncMock()):
            result = await remote.get_active_activities()

        assert len(result) == 1
        assert result[0].id == "a1"


class TestContextManager:
    async def test_close_called_on_exit(self, remote: Remote):
        with patch.object(remote, "close", new=AsyncMock()) as mock_close:
            async with remote:
                pass
        mock_close.assert_called_once()
