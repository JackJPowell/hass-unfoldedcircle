"""Unfolded Circle Remote Web Socket Module"""

import asyncio
import logging
from typing import Callable, Coroutine
from urllib.parse import urlparse

import websockets
from requests import Session
from .websocket import Websocket

from .const import AUTH_APIKEY_NAME, WS_RECONNECTION_DELAY

_LOGGER = logging.getLogger(__name__)


class RemoteWebsocket(Websocket):
    """Web Socket Class for Unfolded Circle Remote"""

    session: Session | None
    hostname: str
    endpoint: str
    api_key_name = AUTH_APIKEY_NAME
    api_key: str = None
    websocket: None

    def __init__(self, api_url: str, api_key: str = None) -> None:
        super().__init__(api_url, api_key)
        self.session = None
        self.hostname = urlparse(api_url).hostname
        self.api_key = api_key
        self.websocket = None

        if urlparse(api_url).scheme == "https":
            self.protocol = "wss"
        else:
            self.protocol = "ws"

        self.endpoint = f"{self.protocol}://{self.hostname}/ws"
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
            "UnfoldedCircleRemote websocket init connection to %s",
            self.endpoint,
        )

        first = True
        async for websocket in websockets.connect(
            self.endpoint,
            additional_headers={"API-KEY": self.api_key},
            ping_interval=30,
            ping_timeout=30,
            close_timeout=20,
        ):
            try:
                _LOGGER.debug("UnfoldedCircleRemote websocket connection initialized")
                self.websocket = websocket
                if first:
                    first = False
                else:
                    asyncio.create_task(reconnection_callback())
                asyncio.create_task(self.subscribe_events())

                while True:
                    async for message in websocket:
                        try:
                            asyncio.create_task(receive_callback(message))
                        except Exception as ex:
                            _LOGGER.debug(
                                "UCR exception in websocket receive callback %s",
                                ex,
                            )
            except websockets.ConnectionClosed as error:
                _LOGGER.debug(
                    "UCR websocket closed. Waiting before reconnecting... %s",
                    error,
                )
                await asyncio.sleep(WS_RECONNECTION_DELAY)
                continue
        _LOGGER.error("UCR exiting init_websocket, this is not normal")
