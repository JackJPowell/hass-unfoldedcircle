"""Unfolded Circle Remote Web Socket Module"""

import asyncio
import json
import logging
from typing import Callable, Coroutine
from urllib.parse import urlparse

import requests
import websockets
from requests import Session
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
        # xff = websocket.request_headers.get("X-Forwarded-For")
        return f"{websocket.id} {msg}", kwargs


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
                    # Call reconnection callback after reconnection success:
                    # useful to extract fresh information with APIs after a
                    # long period of disconnection (sleep)
                    asyncio.ensure_future(reconnection_callback())
                # Subscribe to events we are interested in
                asyncio.ensure_future(self.subscribe_events())

                while True:
                    async for message in websocket:
                        try:
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
        _LOGGER.error("UnfoldedCircleRemote exiting init_websocket, this is not normal")

    def create_api_key(self):
        """Create API key using rest API. Need to call login_api first"""
        response = self.session.post(
            self.api_endpoint + "/auth/api_keys",
            json={"name": self.api_key_name, "scopes": ["admin"]},
        )
        response.raise_for_status()
        data = response.json()
        _LOGGER.info("API key : %s \n", json.dumps(data))
        self.api_key = data["api_key"]

    def delete_api_key(self):
        """Delete registered API key. Need to call login_api first."""
        response = self.session.get(self.api_endpoint + "/auth/api_keys")
        response.raise_for_status()
        api_key_id = None
        for api_key in response.json():
            _LOGGER.info(api_key["key_id"] + ":" + api_key["name"] + "\n")
            if api_key["name"] == self.api_key_name:
                api_key_id = api_key["key_id"]
                break
        if api_key_id is None:
            return
        response = self.session.delete(
            self.api_endpoint + "/auth/api_keys/" + api_key_id
        )
        response.raise_for_status()
        data = response.json()
        _LOGGER.info("API key deleted: %s \n", json.dumps(data))

    def login_api(self, username: str, password: str) -> Session:
        """Login to the remote using rest API with basic
        authentication with the provided username/password."""
        self.session = requests.session()
        response = self.session.post(
            self.api_endpoint + "/pub/login",
            json={"username": username, "password": password},
        )
        data = response.json()
        response.raise_for_status()
        _LOGGER.info(
            "Login {} {}\n".format(json.dumps(data), self.session.cookies["id"])
        )
        return self.session

    def logout_api(self):
        """Logout from the rest API session."""
        if self.session is None:
            return
        response = self.session.post(
            self.api_endpoint + "/pub/logout",
            params={"id": self.session.cookies["id"]},
        )
        _LOGGER.info("Logout %d", response.status_code)
        self.session = None
