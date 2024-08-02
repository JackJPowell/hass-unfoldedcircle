"""Unfolded Circle Dock Web Socket Module"""

import asyncio
import json
import logging
from typing import Callable, Coroutine
from urllib.parse import urlparse
import websockets
from requests import Session
from websockets import WebSocketClientProtocol

from .const import AUTH_APIKEY_NAME, WS_RECONNECTION_DELAY

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

    def __init__(self, api_url: str, api_key: str = None) -> None:
        self.session = None
        self.hostname = urlparse(api_url).hostname
        self.api_key = api_key
        self.websocket = None

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
        """Initialize websocket connection with the registered API key."""
        await self.close_websocket()
        _LOGGER.debug(
            "UnfoldedCircleDock websocket init connection to %s", self.endpoint
        )

        first = True
        async for websocket in websockets.connect(
            self.endpoint,
            # logger=LoggerAdapter(logger, None),
            ping_interval=30,
            ping_timeout=30,
            close_timeout=20,
        ):
            try:
                _LOGGER.debug(
                    "UnfoldedCircleDock websocket connection initialized"
                )
                self.websocket = websocket

                if first:
                    first = False
                else:
                    # Call reconnection callback after reconnection success:
                    # useful to extract fresh information with APIs after a
                    # long period of disconnection (sleep)
                    asyncio.ensure_future(reconnection_callback())
                # Subscribe to events we are interested in

                while True:
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            _LOGGER.debug(
                                "RC2 received websocket message %s", data
                            )
                            if data["type"] == "auth_required":
                                asyncio.ensure_future(
                                    self.send_message({
                                        "type": "auth",
                                        "token": "0149",
                                    })
                                )
                            asyncio.ensure_future(receive_callback(message))
                        except Exception as ex:
                            _LOGGER.debug(
                                "UnfoldedCircleRemote exception in websocket receive callback %s",
                                ex,
                            )
            except websockets.ConnectionClosed as error:
                _LOGGER.debug(
                    "UnfoldedCircleRemote websocket closed. Waiting before reconnecting... %s",
                    error,
                )
                await asyncio.sleep(WS_RECONNECTION_DELAY)
                continue
        _LOGGER.error(
            "UnfoldedCircleRemote exiting init_websocket, this is not normal"
        )

    async def close_websocket(self):
        """Terminate web socket connection"""
        if self.websocket is not None:
            await self.websocket.close(
                1001, "Close connection"
            )  # 1001 : going away
            self.websocket = None

    async def subscribe_events(self) -> None:
        """Subscribe to necessary events."""
        _LOGGER.debug(
            "UnfoldedCircleRemote subscribing to events %s",
            self.events_to_subscribe,
        )
        await self.send_message({
            "id": 1,
            "kind": "req",
            "msg": "subscribe_events",
            "msg_data": {"channels": self.events_to_subscribe},
        })

    async def send_message(self, message: any) -> None:
        """Send a message to the connected websocket."""
        try:
            await self.websocket.send(json.dumps(message))
        except Exception as ex:
            _LOGGER.warning(
                "UnfoldedCircleRemote error while sending message to remote %s",
                ex,
            )
            raise ex
