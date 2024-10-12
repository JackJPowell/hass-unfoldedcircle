"""Unfolded Circle Dock Web Socket Module"""

import json
import logging
from typing import Callable, Coroutine
from urllib.parse import urlparse
from requests import Session
from websockets import WebSocketClientProtocol

from .const import AUTH_APIKEY_NAME

_LOGGER = logging.getLogger(__name__)


class LoggerAdapter(logging.LoggerAdapter):
    """Logger class for websocket for debugging.
    Add connection ID and client IP address to websockets logs."""

    def process(self, msg, kwargs):
        try:
            websocket = kwargs["extra"]["websocket"]
        except KeyError:
            return msg, kwargs
        return f"{websocket.id} {msg}", kwargs


class Websocket:
    """Web Socket Class for Unfolded Circle"""

    session: Session | None
    hostname: str
    endpoint: str
    api_key_name = AUTH_APIKEY_NAME
    api_key: str = None
    websocket: WebSocketClientProtocol | None = None

    def __init__(
        self, api_url: str, api_key: str = None, dock_password: str = None
    ) -> None:
        self.session = None
        self.hostname = urlparse(api_url).hostname
        self.api_key = api_key
        self.websocket = None
        self.dock_password = dock_password

        if urlparse(api_url).scheme == "https":
            self.protocol = "wss"
        else:
            self.protocol = "ws"

        self.endpoint = api_url
        self.api_endpoint = api_url
        self.events_to_subscribe = [
            "software_updates",
        ]

    async def init_websocket(
        self,
        receive_callback: Callable[..., Coroutine],
        reconnection_callback: Callable[..., Coroutine],
    ):
        """init_websocket"""
        pass

    async def close_websocket(self):
        """Terminate web socket connection"""
        if self.websocket is not None:
            await self.websocket.close(1001, "Close connection")  # 1001 : going away
            self.websocket = None

    async def subscribe_events(self) -> None:
        """Subscribe to necessary events."""
        _LOGGER.debug(
            "UnfoldedCircle subscribing to events %s",
            self.events_to_subscribe,
        )
        await self.send_message(
            {
                "id": 1,
                "kind": "req",
                "msg": "subscribe_events",
                "msg_data": {"channels": self.events_to_subscribe},
            }
        )

    async def send_message(self, message: any) -> None:
        """Send a message to the connected websocket."""
        try:
            await self.websocket.send(json.dumps(message))
        except Exception as ex:
            _LOGGER.warning(
                "UnfoldedCircle error while sending message %s",
                ex,
            )
            raise ex
