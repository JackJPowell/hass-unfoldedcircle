"""Unfolded Circle Dock Web Socket Module"""

import asyncio
import json
import logging
from typing import Callable, Coroutine
import websockets
from requests import Session
from websockets import WebSocketClientProtocol

from .websocket import Websocket
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


class DockWebsocket(Websocket):
    """Web Socket Class for Unfolded Circle Dock"""

    session: Session | None
    hostname: str
    endpoint: str
    api_key_name = AUTH_APIKEY_NAME
    api_key: str = None
    websocket: WebSocketClientProtocol | None = None

    def __init__(self, api_url: str, api_key: str = None) -> None:
        super().__init__(api_url, api_key)
        self.endpoint = api_url

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
