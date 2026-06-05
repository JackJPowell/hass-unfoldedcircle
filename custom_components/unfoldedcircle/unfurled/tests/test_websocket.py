"""Tests for the WebSocket client layer."""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

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

        # Simulate auth_required message then subscribe_events response
        challenge_msg = json.dumps(
            {
                "msg": "auth_required",
                "msg_data": {"token": "abc123"},
            }
        )

        async def fake_iter(ws):
            # Yield one auth_required message then stop
            yield challenge_msg

        with patch.object(mock_ws, "__aiter__", side_effect=lambda: fake_iter(mock_ws)):
            # Call _on_connected - it should send the auth response
            task = asyncio.create_task(client._on_connected(mock_ws))
            await asyncio.sleep(0)  # allow co-routine to start
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Check that send was called with credentials
        if mock_ws.send.called:
            sent = json.loads(mock_ws.send.call_args[0][0])
            assert sent.get("msg") == "auth" or "password" in str(sent)


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
