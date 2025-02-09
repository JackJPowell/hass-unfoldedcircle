"""Module to interact with the Unfolded Circle Remote Two Dock."""

import logging
import asyncio
import re
import json
from enum import Enum
from urllib.parse import urljoin, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)


class DockCommand(Enum):
    SET_LED_BRIGHTNESS = "SET_LED_BRIGHTNESS"
    IDENTIFY = "IDENTIFY"
    REBOOT = "REBOOT"


class HTTPError(Exception):
    """Raised when an HTTP operation fails."""

    def __init__(self, status_code, message) -> None:
        """Raise HTTP Error."""
        self.status_code = status_code
        self.message = message
        super().__init__(self.message, self.status_code)


class AuthenticationError(Exception):
    """Raised when HTTP login fails."""


class SystemCommandNotFound(Exception):
    """Raised when an invalid system command is supplied."""

    def __init__(self, message) -> None:
        """Raise command no found error."""
        self.message = message
        super().__init__(self.message)


class ExternalSystemNotRegistered(Exception):
    """Raised when an unregistered external system is supplied."""

    def __init__(self, message) -> None:
        """Raise command no found error."""
        self.message = message
        super().__init__(self.message)


class InvalidIRFormat(Exception):
    """Raised when invalid or insufficient IR details are passed."""

    def __init__(self, message) -> None:
        """Raise invalid IR format error."""
        self.message = message
        super().__init__(self.message)


class NoEmitterFound(Exception):
    """Raised when no emitter could be identified from criteria given."""

    def __init__(self, message) -> None:
        """Raise invalid emitter error."""
        self.message = message
        super().__init__(self.message)


class ApiKeyNotFound(Exception):
    """Raised when API Key with given name can't be found.

    Attributes:
        name -- Name of the API Key
        message -- explanation of the error
    """

    def __init__(self, name, message="API key name not found") -> None:
        """Raise API key not found."""
        self.name = name
        self.message = message
        super().__init__(self.message)


class Dock:
    """Unfolded Circle Dock Class."""

    def __init__(
        self,
        dock_id: str,
        apikey: str,
        remote_endpoint: str,
        remote_configuration_url: str,
        name: str = "",
        ws_url: str = "",
        is_active: bool = False,
        model_name: str = "",
        hardware_revision: str = "",
        serial_number: str = "",
        led_brightness: int = 0,
        ethernet_led_brightness: int = 0,
        software_version: str = "",
        state: str = "",
        is_learning_active: bool = False,
    ) -> None:
        """Create a new UC Dock Object."""

        self._ws_endpoint = ws_url
        self._id = dock_id
        self._name = name
        self._password = ""
        self._host_name = ""
        self._software_version = software_version
        self._serial_number = serial_number
        self._model_name = model_name
        self._hardware_revision = hardware_revision
        self._model_number = ""
        self._manufacturer = "Unfolded Circle"
        self._mac_address = dock_id.lower().removeprefix("uc-dock-")
        self._ip_address = ""
        self._is_active = is_active
        self._led_brightness = led_brightness
        self._ethernet_led_brightness = ethernet_led_brightness
        self._state = state
        self._is_learning_active = is_learning_active
        self._learned_code = {}
        self._codesets = []
        self._token = ""
        self._description = ""
        self._check_for_updates = False
        self._automatic_updates = False
        self._available_update = []
        self._latest_software_version = ""
        self._release_notes_url = ""
        self._release_notes = ""
        self._remotes = []
        self._remotes_complete = []
        self.endpoint = remote_endpoint
        self.apikey = apikey
        self._remote_configuration_url = remote_configuration_url
        self.websocket = ""
        self._update_in_progress = False
        self._update_percent = 0

    @property
    def name(self):
        """Name of the dock."""
        return self._name or "Unfolded Circle Dock"

    @property
    def id(self):
        """id of the dock."""
        return self._id

    @property
    def host_name(self):
        """host_name of the dock."""
        return self._host_name

    @property
    def software_version(self):
        """software version of the dock."""
        return self._software_version

    @property
    def serial_number(self):
        """serial number of the dock."""
        return self._serial_number

    @property
    def model_name(self):
        """model_name of the dock."""
        if self._model_name == "UCD2":
            return "Dock Two"
        return self._model_name

    @property
    def hardware_revision(self):
        """hardware_revision of the dock."""
        return self._hardware_revision

    @property
    def model_number(self):
        """model_number of the dock."""
        return self._model_number

    @property
    def manufacturer(self):
        """manufacturer of the dock."""
        return self._manufacturer

    @property
    def mac_address(self):
        """mac_address of the dock."""
        return self._mac_address

    @property
    def ip_address(self):
        """ip_address of the dock."""
        return self._ip_address

    @property
    def is_active(self):
        """Is the dock active"""
        return self._is_active

    @property
    def remotes(self):
        """List of defined remotes."""
        return self._remotes

    @property
    def remotes_complete(self):
        """List of defined remotes_complete."""
        return self._remotes_complete

    @property
    def codesets(self):
        """List of defined codesets."""
        return self._codesets

    @property
    def led_brightness(self):
        """led_brightness of the dock."""
        return self._led_brightness

    @property
    def ethernet_led_brightness(self):
        """ethernet_led_brightness of the dock."""
        return self._ethernet_led_brightness

    @property
    def state(self):
        """state of the dock."""
        return self._state

    @property
    def is_learning_active(self):
        """is_learning_active of the dock."""
        return self._is_learning_active

    @property
    def learned_code(self):
        """Most recent learned code."""
        return self._learned_code

    @property
    def token(self):
        """token of the dock."""
        return self._token

    @property
    def description(self):
        """description of the dock."""
        return self._description

    @property
    def check_for_updates(self):
        """check_for_updates of the dock."""
        return self._check_for_updates

    @property
    def automatic_updates(self):
        """automatic_updates of the dock."""
        return self._automatic_updates

    @property
    def available_update(self):
        """available_update of the dock."""
        return self._available_update

    @property
    def latest_software_version(self):
        """latest_software_version of the dock."""
        return self._latest_software_version

    @property
    def update_in_progress(self):
        """update_in_progress of the dock."""
        return self._update_in_progress

    @property
    def update_percent(self):
        """update_percent of the dock."""
        return self._update_percent

    @property
    def release_notes_url(self):
        """release_notes_url of the dock."""
        return self._release_notes_url

    @property
    def release_notes(self):
        """release_notes of the dock."""
        return self._release_notes

    @property
    def remote_configuration_url(self):
        """remote_configuration_url of the dock."""
        return self._remote_configuration_url

    @property
    def ws_endpoint(self):
        """ws_endpoint of the dock."""
        return self._ws_endpoint

    @property
    def password(self):
        """password of the dock."""
        return self._password

    @property
    def has_password(self):
        """returns true if password of the dock is set."""
        return self._password != ""

    ### URL Helpers ###
    def validate_url(self, uri):
        """Validate passed in URL and attempts to correct api endpoint if path isn't supplied."""
        if re.search("^http.*", uri) is None:
            uri = (
                "http://" + uri
            )  # Normalize to absolute URLs so urlparse will parse the way we want
        parsed_url = urlparse(uri)
        # valdation = set(uri)
        if parsed_url.scheme == "":
            uri = "http://" + uri
        if parsed_url.path == "/":  # Only host supplied
            uri = uri + "api/"
            return uri
        if parsed_url.path == "":
            uri = uri + "/api/"
            return uri
        if (
            parsed_url.path[-1] != "/"
        ):  # User supplied an endpoint, make sure it has a trailing slash
            uri = uri + "/"
        return uri

    def derive_configuration_url(self) -> str:
        """Derive configuration url from endpoint url."""
        parsed_url = urlparse(self.endpoint)
        self.configuration_url = (
            f"{parsed_url.scheme}://{parsed_url.netloc}/configurator/"
        )
        return self.configuration_url

    def url(self, path="/") -> str:
        """Join path with base url."""
        return urljoin(self.endpoint, path)

    @staticmethod
    def url_is_secure(url) -> bool:
        """Returns true if the configuration url is using a secure protocol"""
        parsed_url = urlparse(url)
        if parsed_url.scheme == "https":
            return True
        return False

    ### HTTP methods ###
    def client(self) -> aiohttp.ClientSession:
        """Create a aiohttp client object with needed headers and defaults."""
        if self.apikey:
            headers = {
                "Authorization": "Bearer " + self.apikey,
                "Accept": "application/json",
            }
            return aiohttp.ClientSession(
                headers=headers, timeout=aiohttp.ClientTimeout(total=5)
            )

    async def validate_connection(self) -> bool:
        """Validate we can communicate with the remote given the supplied information."""
        async with (
            self.client() as session,
            session.head(self.url("activities")) as response,
        ):
            if response.status == 401:
                raise AuthenticationError
            return response.status == 200

    async def raise_on_error(self, response):
        """Raise an HTTP error if the response returns poorly."""
        if not response.ok:
            content = await response.json()
            msg = f"{response.status} Request: {content['code']} Reason: {content['message']}"
            raise HTTPError(response.status, msg)
        return response

    async def get_info(self) -> str:
        """Get dock information."""
        async with (
            self.client() as session,
            session.get(self.url(f"docks/devices/{self.id}")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._name = information.get("name")
            self._ws_endpoint = information.get("resolved_ws_url")
            self._is_active = information.get("active")
            self._model_number = information.get("model")
            self._hardware_revision = information.get("revision")
            self._serial_number = information.get("serial")
            self._led_brightness = information.get("led_brightness")
            self._ethernet_led_brightness = information.get("eth_led_brightness")
            self._software_version = information.get("version")
            self._state = information.get("state")
            self._is_learning_active = information.get("learning_active")

            return information

    async def get_update_status(self) -> str:
        """Get dock update information"""
        async with (
            self.client() as session,
            session.get(self.url(f"docks/devices/{self.id}/update")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._latest_software_version = information.get("version")
            self._available_update = information.get("update_available")
            self._check_for_updates = information.get("update_check_enabled")

            return information

    async def update_firmware(self) -> str:
        """Start dock firmware update"""
        information = {}
        async with (
            self.client() as session,
            session.post(self.url(f"docks/devices/{self.id}/update")) as response,
        ):
            if response.ok:
                information = await response.json()
                self._update_in_progress = True
            if response.status == 409:
                information = {"state": "DOWNLOADING"}
            if response.status == 503:
                information = {"state": "NO_BATTERY"}
            return information

    async def start_ir_learning(self) -> str:
        """Start an IR Learning Session"""
        async with (
            self.client() as session,
            session.put(self.url(f"ir/emitters/{self.id}/learn")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()

            return information

    async def stop_ir_learning(self) -> str:
        """Stop an IR learning session"""
        async with (
            self.client() as session,
            session.delete(self.url(f"ir/emitters/{self.id}/learn")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()

            return information

    async def get_remotes(self) -> list:
        """Get list of remotes defined. (IR Remotes as defined by Unfolded Circle)."""
        remote_data = {}
        async with (
            self.client() as session,
            session.get(self.url("remotes")) as response,
        ):
            await self.raise_on_error(response)
            remotes = await response.json()
            for remote in remotes:
                if remote.get("enabled") is True:
                    remote_data = {
                        "name": remote.get("name").get("en"),
                        "entity_id": remote.get("entity_id"),
                    }
                    self._remotes.append(remote_data.copy())
            return self._remotes

    async def get_remotes_complete(self) -> list:
        """Get list of remotes defined. (IR Remotes as defined by Unfolded Circle)."""
        if not self.remotes:
            await self.get_remotes()

        for remote in self.remotes:
            entity_id = remote.get("entity_id")
            async with (
                self.client() as session,
                session.get(self.url(f"remotes/{entity_id}")) as response,
            ):
                await self.raise_on_error(response)
                remote_info = await response.json()
                self._remotes_complete.append(remote_info.copy())
        return self._remotes_complete

    async def get_custom_codesets(self) -> list:
        """Get list of custom ir codesets."""
        async with (
            self.client() as session,
            session.get(self.url("ir/codes/custom")) as response,
        ):
            await self.raise_on_error(response)
            codesets = await response.json()
            self._codesets = codesets
            return self._codesets

    async def create_remote(
        self, name: str, device: str, description: str, icon: str = "uc:movie"
    ) -> dict:
        """Create a new remote codeset. (IR Remotes as defined by Unfolded Circle)."""
        remote_data = {
            "name": {"en": f"{name}"},
            "icon": f"{icon}",
            "description": {"en": f"{description}"},
            "custom_codeset": {
                "manufacturer_id": "custom",
                "device_name": f"{device}",
                "device_type": "various",
            },
        }
        async with (
            self.client() as session,
            session.post(self.url("remotes"), json=remote_data) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def add_remote_command_to_codeset(
        self,
        remote_entity_id: str,
        command_id: str,
        value: str,
        ir_format: str,
        update_if_exists: bool = True,
    ) -> list:
        """Get list of remote codesets."""
        ir_data = {"value": f"{value}", "format": f"{ir_format}"}
        async with (
            self.client() as session,
            session.post(
                self.url(f"remotes/{remote_entity_id}/ir/{command_id}"),
                json=ir_data,
            ) as response,
        ):
            codeset = await response.json()
            if response.status == 422:
                if update_if_exists:
                    codeset = await self.update_remote_command_in_codeset(
                        remote_entity_id, command_id, value, ir_format
                    )
                    return codeset
                else:
                    await self.raise_on_error(response)

            if response.ok:
                return codeset

    async def update_remote_command_in_codeset(
        self,
        remote_entity_id: str,
        command_id: str,
        value: str,
        ir_format: str,
    ) -> list:
        """Update command in remote codesets."""
        ir_data = {"value": f"{value}", "format": f"{ir_format}"}
        async with (
            self.client() as session,
            session.patch(
                self.url(f"remotes/{remote_entity_id}/ir/{command_id}"),
                json=ir_data,
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def send_command(
        self, command: DockCommand, command_value: str = None
    ) -> str:
        """Send a command to the dock"""
        payload = {"command": f"{command}"}
        if command_value:
            payload = {"command": f"{command}", "value": f"{command_value}"}
        async with (
            self.client() as session,
            session.post(
                self.url(f"docks/devices/{self.id}/command"), json=payload
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    def update_from_message(self, message: any) -> None:
        """Update internal data from received websocket messages"""
        data = json.loads(message)
        _LOGGER.debug("RC2 received websocket message %s", data)
        try:
            if data["type"] == "auth_required":
                _LOGGER.debug("auth is required")
            if data["msg"] == "ir_receive":
                self._learned_code = data.get("ir_code")
            if data["msg"] == "dock_update_change":
                self._update_percent = data.get("progress")
                self._update_in_progress = True
        except Exception:
            pass

    async def update(self):
        """Updates all information about the remote."""
        _LOGGER.debug("Unfoldded circle remote update data")
        group = asyncio.gather(
            self.get_info(),
            self.get_update_status(),
        )
        await group

        _LOGGER.debug("Unfoldded circle remote data updated")
