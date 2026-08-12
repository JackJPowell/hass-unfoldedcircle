"""Tests for Dock initialization and WebSocket auth flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aioresponses import aioresponses

from unfurled.dock import Dock
from unfurled.helpers.models import DockCommand, DockCommunicationMode

BASE_URL = "http://192.168.1.10/api/"
API_KEY = "test-key"
DOCK_WS = "ws://192.168.1.20:8080/ws"


DOCK_DATA = {
    "dock_id": "uc-dock-aa:bb:cc:dd:ee:01",
    "name": "My Dock",
    "ws_url": DOCK_WS,
    "active": True,
    "model_number": "UCD2",
    "hardware_revision": "rev1",
    "serial_number": "UCD2-001",
    "led_brightness": 50,
    "ethernet_led_brightness": 50,
    "software_version": "1.0.0",
    "state": "CONNECTED",
}


class TestDockFromDict:
    def test_parses_id(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.device.id == "uc-dock-aa:bb:cc:dd:ee:01"

    def test_parses_name(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.device.name == "My Dock"

    def test_parses_ws_url(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.ws_url == DOCK_WS

    def test_parses_resolved_ws_url(self):
        data = {**DOCK_DATA, "ws_url": "", "resolved_ws_url": DOCK_WS}
        dock = Dock.from_dict(
            data, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.ws_url == DOCK_WS

    def test_parses_led_brightness(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.state.led_brightness == 20
        assert dock.state.led_brightness_native == 50

    def test_parses_state(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.state.state == "CONNECTED"

    def test_is_active(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.state.is_active is True


class TestDockRestCommands:
    @pytest.fixture
    def dock(self) -> Dock:
        return Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )

    async def test_send_command_reboot(self, dock: Dock):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}docks/devices/{dock.device.id}/command",
                payload={"status": "ok"},
            )
            await dock.system._send_command(DockCommand.REBOOT)

    async def test_set_led_brightness(self, dock: Dock):
        dock.api.post_dock_command = AsyncMock(return_value={"status": "ok"})

        await dock.system.set_led_brightness(75)

        dock.api.post_dock_command.assert_awaited_once_with(
            dock.device.id,
            {"command": "SET_LED_BRIGHTNESS", "value": "191"},
        )
        assert dock.state.led_brightness == 75

    async def test_identify_sends_command(self, dock: Dock):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}docks/devices/{dock.device.id}/command",
                payload={"status": "ok"},
            )
            await dock.system.identify()

    async def test_reboot_sends_command(self, dock: Dock):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}docks/devices/{dock.device.id}/command",
                payload={"status": "ok"},
            )
            await dock.system.reboot()


class TestDockWsMessageHandling:
    @pytest.fixture
    def dock(self) -> Dock:
        return Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )

    async def test_learning_message_stores_code(self, dock: Dock):
        raw = json.dumps(
            {
                "msg": "ir_learn",
                "msg_data": {
                    "format": "HEX",
                    "data": "0x1234ABCD",
                },
            }
        )
        await dock._handle_ws_message(raw)
        assert dock._learned_code is not None
        assert dock._learned_code.get("format") == "HEX"

    async def test_unknown_message_ignored(self, dock: Dock):
        raw = json.dumps({"msg": "unknown", "msg_data": {}})
        await dock._handle_ws_message(raw)  # should not raise

    async def test_invalid_json_ignored(self, dock: Dock):
        await dock._handle_ws_message("not json")  # should not raise

    async def test_sysinfo_message_updates_volume(self, dock: Dock):
        dock.device.model_number = "UCD3"
        await dock._handle_ws_message(json.dumps({"msg": "get_sysinfo", "volume": 42}))
        assert dock.state.volume == 42

    async def test_learning_events_update_state(self, dock: Dock):
        await dock._handle_ws_message(json.dumps({"type": "event", "msg": "ir_receive_on"}))
        assert dock.state.is_learning_active is True

        await dock._handle_ws_message(json.dumps({"type": "event", "msg": "ir_receive_off"}))
        assert dock.state.is_learning_active is False

    async def test_port_mode_event_updates_external_port_state(self, dock: Dock):
        await dock._handle_ws_message(
            json.dumps(
                {
                    "type": "event",
                    "msg": "port_mode",
                    "port": 1,
                    "mode": "AUTO",
                    "active_mode": "IR_BLASTER",
                }
            )
        )

        port = dock.state.external_ports[1]
        assert port.mode == "AUTO"
        assert port.active_mode == "IR_BLASTER"

    async def test_port_mode_response_updates_external_port_state(self, dock: Dock):
        await dock._handle_ws_message(
            json.dumps(
                {
                    "type": "dock",
                    "msg": "get_port_mode",
                    "port": 1,
                    "mode": "IR_EMITTER_MONO_PLUG",
                }
            )
        )

        assert dock.state.external_ports[1].mode == "IR_EMITTER_MONO_PLUG"

    async def test_sysinfo_message_updates_all_external_ports(self, dock: Dock):
        await dock._handle_ws_message(
            json.dumps(
                {
                    "msg": "get_sysinfo",
                    "ports": [
                        {"port": 1, "mode": "IR_BLASTER"},
                        {"port": 2, "mode": "TRIGGER_5V"},
                    ],
                }
            )
        )

        assert {port: value.mode for port, value in dock.state.external_ports.items()} == {
            1: "IR_BLASTER",
            2: "TRIGGER_5V",
        }


class TestDockDirectTransport:
    @pytest.fixture
    def dock(self) -> Dock:
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        dock.configure_communication(DockCommunicationMode.DIRECT, "0000")
        return dock

    async def test_led_brightness_uses_direct_command(self, dock: Dock):
        dock._direct_request = AsyncMock(return_value={"code": 200})
        await dock.system.set_led_brightness(75)
        dock._direct_request.assert_awaited_once_with("set_brightness", status_led=191, eth_led=191)
        assert dock.state.led_brightness == 75

    async def test_direct_ir_maps_port_mask(self, dock: Dock):
        dock._ws_client = AsyncMock()
        dock._ws_client.is_connected = True
        dock._direct_request = AsyncMock(return_value={"code": 200})
        assert await dock.send_ir("4;0x10;12;0", "HEX", port_mask=5, repeat=2)
        dock._direct_request.assert_awaited_once_with(
            "ir_send",
            code="4;0x10;12;0",
            format="hex",
            repeat=2,
            int_side=True,
            int_top=False,
            ext1=True,
            ext2=False,
        )

    async def test_set_volume_uses_direct_dock_three_command(self, dock: Dock):
        dock.device.model_number = "UCD3"
        dock._ws_client = AsyncMock()
        dock._ws_client.is_connected = True
        dock._direct_request = AsyncMock(return_value={"code": 200})

        await dock.system.set_volume(42)

        dock._direct_request.assert_awaited_once_with("set_volume", volume=42)
        assert dock.system.volume == 42

    async def test_get_volume_refreshes_direct_sysinfo(self, dock: Dock):
        dock.device.model_number = "UCD3"
        dock._ws_client = AsyncMock()
        dock._ws_client.is_connected = True
        dock._direct_request = AsyncMock(return_value={"volume": 42})

        assert await dock.system.get_volume() == 42
        dock._direct_request.assert_awaited_once_with("get_sysinfo")

    async def test_set_volume_rejects_unsupported_dock(self, dock: Dock):
        with pytest.raises(NotImplementedError, match="Dock 3"):
            await dock.system.set_volume(42)

    async def test_set_volume_validates_range(self, dock: Dock):
        dock.device.model_number = "UCD3"
        with pytest.raises(ValueError, match="between 0 and 100"):
            await dock.system.set_volume(101)


class TestDockClose:
    async def test_close_disconnects_websocket(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        mock_ws = AsyncMock()
        dock._ws_client = mock_ws
        await dock.close()
        mock_ws.disconnect.assert_called_once()
