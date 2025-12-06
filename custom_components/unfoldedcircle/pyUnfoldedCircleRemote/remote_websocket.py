"""Unfolded Circle Remote Web Socket Module"""

import asyncio
import logging
from typing import Callable, Coroutine

import websockets
from requests import Session
from .websocket import Websocket

from .const import AUTH_APIKEY_NAME

_LOGGER = logging.getLogger(__name__)


class RemoteWebsocket(Websocket):
    """Web Socket Class for Unfolded Circle Remote"""

    session: Session | None
    hostname: str
    endpoint: str
    api_key_name = AUTH_APIKEY_NAME
    api_key: str = None
    websocket: None
    _reconnect_count: int = 0
    _message_count: int = 0

    async def init_websocket(
        self,
        receive_callback: Callable[..., Coroutine],
        reconnection_callback: Callable[..., Coroutine],
    ):
        """Initialize websocket connection with the registered API key."""
        await self.close_websocket()
        _LOGGER.warning(
            "UnfoldedCircleRemote websocket initializing connection to %s",
            self.endpoint,
        )

        first = True
        reconnect_delay = 5  # seconds

        async for websocket in websockets.connect(
            self.endpoint,
            additional_headers={"API-KEY": self.api_key},
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
        ):
            try:
                self.websocket = websocket

                if first:
                    first = False
                    _LOGGER.warning(
                        "UnfoldedCircleRemote websocket connection established to %s",
                        self.endpoint,
                    )
                else:
                    self._reconnect_count += 1
                    _LOGGER.warning(
                        "UnfoldedCircleRemote websocket reconnected to %s (reconnect #%d, total messages received: %d)",
                        self.endpoint,
                        self._reconnect_count,
                        self._message_count,
                    )

                    try:
                        _LOGGER.warning(
                            "UnfoldedCircleRemote starting state resynchronization after reconnect"
                        )
                        await reconnection_callback()
                        _LOGGER.warning(
                            "UnfoldedCircleRemote state resynchronization completed successfully"
                        )
                    except Exception as ex:
                        _LOGGER.error(
                            "UnfoldedCircleRemote FAILED to resynchronize state after reconnect: %s. This may cause stale data in Home Assistant until integration is reloaded.",
                            ex,
                            exc_info=True,
                        )

                # Subscribe to events after reconnection
                try:
                    await self.subscribe_events()
                    _LOGGER.info(
                        "UnfoldedCircleRemote successfully subscribed to events: %s",
                        self.events_to_subscribe
                        if hasattr(self, "events_to_subscribe")
                        else "default",
                    )
                except Exception as ex:
                    _LOGGER.error(
                        "UnfoldedCircleRemote FAILED to subscribe to events: %s. Updates may not be received until reconnection.",
                        ex,
                        exc_info=True,
                    )

                while True:
                    async for message in websocket:
                        self._message_count += 1

                        # Log periodic message stats to help with debugging
                        if self._message_count % 100 == 0:
                            _LOGGER.info(
                                "UnfoldedCircleRemote processed %d total messages (reconnects: %d)",
                                self._message_count,
                                self._reconnect_count,
                            )

                        try:
                            asyncio.create_task(receive_callback(message))
                        except Exception as ex:
                            _LOGGER.error(
                                "UnfoldedCircleRemote exception in websocket receive callback: %s",
                                ex,
                                exc_info=True,
                            )

            except websockets.ConnectionClosed as error:
                _LOGGER.warning(
                    "UnfoldedCircleRemote websocket connection closed (code: %s, reason: %s). Waiting %d seconds before attempting reconnect #%d...",
                    error.code if hasattr(error, "code") else "unknown",
                    error.reason if hasattr(error, "reason") else "unknown",
                    reconnect_delay,
                    self._reconnect_count + 1,
                )
                await asyncio.sleep(reconnect_delay)
                continue
            except asyncio.CancelledError:
                _LOGGER.warning(
                    "UnfoldedCircleRemote websocket connection cancelled (shutdown requested)"
                )
                raise
            except Exception as ex:
                _LOGGER.error(
                    "UnfoldedCircleRemote unexpected websocket error: %s. Waiting %d seconds before attempting reconnect #%d...",
                    ex,
                    reconnect_delay,
                    self._reconnect_count + 1,
                    exc_info=True,
                )
                await asyncio.sleep(reconnect_delay)
                continue

        _LOGGER.error(
            "UnfoldedCircleRemote exited init_websocket loop abnormally. This should not happen and indicates a critical error. Total reconnects: %d, messages: %d",
            self._reconnect_count,
            self._message_count,
        )
