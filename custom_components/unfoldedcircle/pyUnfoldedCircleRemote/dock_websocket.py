"""Unfolded Circle Dock Web Socket Module"""

import asyncio
import json
import logging
from typing import Callable, Coroutine
import websockets

from .websocket import Websocket
from .const import WS_RECONNECTION_DELAY

_LOGGER = logging.getLogger(__name__)


class DockWebsocket(Websocket):
    """Web Socket Class for Unfolded Circle Dock"""

    def __init__(
        self, api_url: str, api_key: str = None, dock_password: str = None
    ) -> None:
        super().__init__(api_url, api_key, dock_password)
        self.endpoint = api_url
        self.awaits_password = True
        self.events_to_subscribe = [
            "all",
        ]

    async def init_websocket(
        self,
        receive_callback: Callable[..., Coroutine],
        reconnection_callback: Callable[..., Coroutine],
        validate_password: bool = False,
    ):
        """Initialize websocket connection with the dock password."""
        if self.dock_password:
            await self.close_websocket()
            _LOGGER.debug(
                "UnfoldedCircleDock websocket init connection to %s",
                self.endpoint,
            )

            first = True
            async for websocket in websockets.connect(
                self.endpoint,
                ping_interval=30,
                ping_timeout=30,
                close_timeout=20,
            ):
                try:
                    _LOGGER.debug("UnfoldedCircleDock websocket connection initialized")
                    self.websocket = websocket

                    if first:
                        first = False
                    else:
                        if reconnection_callback is not None:
                            asyncio.create_task(reconnection_callback())
                    asyncio.create_task(self.subscribe_events())

                    while True:
                        async for message in websocket:
                            try:
                                data = json.loads(message)
                                _LOGGER.debug("RC2 received websocket message %s", data)
                                if data.get("type") == "auth_required":
                                    asyncio.create_task(
                                        self.send_message(
                                            {
                                                "type": "auth",
                                                "token": f"{self.dock_password}",
                                            }
                                        )
                                    )
                                if receive_callback is not None:
                                    asyncio.create_task(receive_callback(message))
                            except Exception as ex:
                                _LOGGER.error(
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

    async def is_password_valid(self):
        """Initialize websocket connection with the dock password."""
        if self.dock_password:
            return await self.init_websocket(self.receive_message, None, True)

    async def receive_message(self, message: any) -> None:
        """Receive a message from the connected websocket."""
        try:
            data = json.loads(message)
            try:
                if data["type"] == "authentication":
                    await self.close_websocket()
                    if data["code"] == 200:
                        return True
                    return False
            except Exception:
                await self.close_websocket()
            _LOGGER.debug("UCD received websocket message %s", data)
        except Exception as ex:
            _LOGGER.warning(
                "UCD exception in websocket receive callback %s",
                ex,
            )
