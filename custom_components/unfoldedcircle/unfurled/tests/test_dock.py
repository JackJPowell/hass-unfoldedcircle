"""Tests for Dock initialization and WebSocket auth flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aioresponses import aioresponses

from unfurled.dock import Dock
from unfurled.helpers.models import DockCommand

BASE_URL = "http://192.168.1.10/api/"
API_KEY = "test-key"
DOCK_WS = "ws://192.168.1.20:8080/ws"


DOCK_DATA = {
    "entity_id": "uc-dock-aa:bb:cc:dd:ee:01",
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

    def test_parses_led_brightness(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        assert dock.state.led_brightness == 50

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
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}docks/devices/{dock.device.id}/command",
                payload={"status": "ok"},
            )
            m.put(
                f"{BASE_URL}docks/{dock.device.id}",
                payload={"led_brightness": 75},
            )
            await dock.system.set_led_brightness(75)
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


class TestDockClose:
    async def test_close_disconnects_websocket(self):
        dock = Dock.from_dict(
            DOCK_DATA, api_key=API_KEY, remote_endpoint=BASE_URL, remote_configuration_url=""
        )
        mock_ws = AsyncMock()
        dock._ws_client = mock_ws
        await dock.close()
        mock_ws.disconnect.assert_called_once()
