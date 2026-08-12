"""Tests for the WebSocket client layer."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from unfurled.helpers.websocket import DockWebSocketClient, RemoteWebSocketClient, WebSocketClient

BASE_URL = "http://192.168.1.10/api/"
API_KEY = "test-key"


class TestWebSocketClientCallbacks:
    def test_register_message_callback(self):
        client = WebSocketClient("ws://host/ws")
        cb = AsyncMock()
        client.on_message(cb)
        assert cb in client._message_callbacks

    def test_register_connect_callback(self):
        client = WebSocketClient("ws://host/ws")
        cb = AsyncMock()
        client.on_connect(cb)
        assert cb in client._connect_callbacks

    def test_register_disconnect_callback(self):
        client = WebSocketClient("ws://host/ws")
        cb = AsyncMock()
        client.on_disconnect(cb)
        assert cb in client._disconnect_callbacks


class TestWebSocketClientIsConnected:
    def test_not_connected_initially(self):
        client = WebSocketClient("ws://host/ws")
        assert client.is_connected is False


class TestRemoteWebSocketClient:
    def test_endpoint_derived_from_http_url(self):
        client = RemoteWebSocketClient("http://192.168.1.10/api/", "key")
        assert client._endpoint == "ws://192.168.1.10/ws"

    def test_endpoint_derived_from_https_url(self):
        client = RemoteWebSocketClient("https://192.168.1.10/api/", "key")
        assert client._endpoint == "wss://192.168.1.10/ws"

    def test_api_key_in_extra_headers(self):
        client = RemoteWebSocketClient("http://192.168.1.10/api/", "my-secret")
        headers = client._extra_connect_headers()
        assert headers.get("API-KEY") == "my-secret"

    async def test_on_connected_sends_subscribe(self):
        client = RemoteWebSocketClient("http://host/api/", API_KEY)
        mock_ws = AsyncMock()
        # _on_connected calls self.send() which checks self._ws
        client._ws = mock_ws
        await client._on_connected(mock_ws)

        sent_text = mock_ws.send.call_args[0][0]
        sent = json.loads(sent_text)
        assert sent["msg"] == "subscribe_events"
        assert "all" in sent["msg_data"]["channels"]


class TestDockWebSocketClient:
    def test_endpoint_stored(self):
        client = DockWebSocketClient("ws://192.168.1.20:8080/ws", "password")
        assert client._endpoint == "ws://192.168.1.20:8080/ws"

    async def test_on_connected_sends_auth_when_challenged(self):
        client = DockWebSocketClient("ws://host/ws", "secret")
        mock_ws = AsyncMock()

        mock_ws.recv.side_effect = [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth", "msg": "authentication", "code": 200}),
        ]
        client._ws = mock_ws
        await client._on_connected(mock_ws)
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent == {"type": "auth", "token": "secret"}

    async def test_request_resolves_correlated_response(self):
        client = DockWebSocketClient("ws://host/ws", "secret")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        task = asyncio.create_task(client.request("get_sysinfo"))
        await asyncio.sleep(0)
        await client._handle_response(
            json.dumps({"type": "dock", "req_id": 1, "msg": "get_sysinfo", "code": 200})
        )
        assert (await task)["msg"] == "get_sysinfo"
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent == {"type": "dock", "id": 1, "command": "get_sysinfo"}


class TestWebSocketDisconnect:
    async def test_disconnect_cancels_task(self):
        client = WebSocketClient("ws://host/ws")

        # Create a dummy task that runs forever
        async def run_forever():
            await asyncio.sleep(999)

        task = asyncio.create_task(run_forever())
        client._task = task
        client._running = True

        await client.disconnect()
        assert not client._running
        assert task.cancelled() or task.done()

    async def test_send_when_not_connected_is_safe(self):
        client = WebSocketClient("ws://host/ws")
        # Should not raise even when not connected
        await client.send({"msg": "test"})
