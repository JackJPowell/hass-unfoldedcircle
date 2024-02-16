import json
import logging
import asyncio
import re
from typing import Callable

import websockets
import requests
from requests import Session
from websockets import WebSocketClientProtocol

from .const import AUTH_APIKEY_NAME, WS_RECONNECTION_DELAY

_LOGGER = logging.getLogger(__name__)


def parse_hostname(uri):
    """Validate passed in URL and attempts to correct websocket endpoint."""
    parsed_url = re.sub("^http.*://", "", uri)
    parsed_url = re.sub("/*api/*$", "", parsed_url)
    parsed_url = re.sub("/$", "", parsed_url)
    return parsed_url


class RemoteWebsocket:
    session: Session | None
    hostname: str
    endpoint: str
    api_key_name = AUTH_APIKEY_NAME
    api_key: str = None
    websocket: WebSocketClientProtocol | None = None

    def __init__(self, hostname: str, api_key: str = None) -> None:
        self.session = None
        self.hostname = parse_hostname(hostname)
        self.api_key = api_key
        self.websocket = None
        self.endpoint = "ws://"+self.hostname+"/ws"
        self.api_endpoint = "http://"+self.hostname + "/api"
        self.events_to_subscribe = [
                "software_updates",
            ]

    async def init_websocket(self, receive_callback: Callable[[any], None], reconnection_callback: Callable[[], None]):
        """Initialize websocket connection with the registered API key."""
        await self.close_websocket()
        _LOGGER.debug("UnfoldedCircleRemote websocket init connection to %s", self.endpoint)
        first = True
        async for websocket in websockets.connect(self.endpoint, extra_headers={"API-KEY": self.api_key}):
            try:
                _LOGGER.debug("UnfoldedCircleRemote websocket connection initialized")
                self.websocket = websocket
                await self.subscribe_events()
                # Call reconnection callback after reconnection success:
                # useful to extract fresh information with APIs after a long period of disconnection (sleep)
                if first:
                    first = False
                else:
                    reconnection_callback()
                while True:
                    async for message in websocket:
                        try:
                            receive_callback(message)
                        except Exception as ex:
                            _LOGGER.debug("UnfoldedCircleRemote exception in websocket receive callback", ex)
            except websockets.ConnectionClosed:
                _LOGGER.debug("UnfoldedCircleRemote websocket closed. Waiting before reconnecting...")
                await asyncio.sleep(WS_RECONNECTION_DELAY)
                continue
    async def close_websocket(self):
        if self.websocket is not None:
            await self.websocket.close(1001, "Close connection") # 1001 : going away
            self.websocket = None

    async def subscribe_events(self):
        """Subscribe to necessary events."""
        # Available channels :
        # "all" "configuration" "entities" "entity_button" "entity_switch" "entity_climate" "entity_cover"
        # "entity_light" "entity_media_player" "entity_sensor" "entity_activity" "entity_macro" "entity_remote" "activity_groups" "integrations"
        # "profiles" "emitters" "docks" "software_update" "battery_status" "ambient_light"
        _LOGGER.debug("UnfoldedCircleRemote subscribing to events %s", self.events_to_subscribe)
        await self.send_message({"id": 1, "kind": "req", "msg": "subscribe_events", "msg_data": {
            "channels": self.events_to_subscribe
        }})

    async def send_message(self, message: any):
        """Send a message to the connected websocket."""
        try:
            await self.websocket.send(json.dumps(message))
        except Exception as ex:
            _LOGGER.warning("UnfoldedCircleRemote error while sending message to remote", ex)

    def create_api_key(self):
        """Create API key using rest API. Need to call login_api first"""
        response = self.session.post(self.api_endpoint + "/auth/api_keys",
                                     json={"name": self.api_key_name, "scopes": ["admin"]})
        response.raise_for_status()
        data = response.json()
        _LOGGER.info("API key : " + json.dumps(data) + "\n")
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
        response = self.session.delete(self.api_endpoint + "/auth/api_keys/" + api_key_id)
        response.raise_for_status()
        data = response.json()
        _LOGGER.info("API key deleted: " + json.dumps(data) + "\n")

    def login_api(self, username: str, password: str) -> Session:
        """Login to the remote using rest API with basic authentication with the provided username/password."""
        self.session = requests.session()
        response = self.session.post(self.api_endpoint + "/pub/login",
                                     json={"username": username, "password": password})
        data = response.json()
        response.raise_for_status()
        _LOGGER.info("Login {} {}\n".format(json.dumps(data), self.session.cookies["id"]))
        return self.session

    def logout_api(self):
        """Logout from the rest API session."""
        if self.session is None:
            return
        response = self.session.post(self.api_endpoint + "/pub/logout", params={"id": self.session.cookies["id"]})
        _LOGGER.info("Logout %d", response.status_code)
        self.session = None
