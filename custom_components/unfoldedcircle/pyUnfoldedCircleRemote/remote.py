"""Module to interact with the Unfolded Circle Remote Two."""

import asyncio
import copy
import json
import logging
import re
import socket
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from wakeonlan import send_magic_packet
from packaging.version import Version


import aiohttp
import zeroconf

from .const import (
    AUTH_APIKEY_NAME,
    AUTH_USERNAME,
    SIMULATOR_MAC_ADDRESS,
    SYSTEM_COMMANDS,
    ZEROCONF_SERVICE_TYPE,
    ZEROCONF_TIMEOUT,
    RemotePowerModes,
    RemoteUpdateType,
    SIMULATOR_NAMES,
)
from .dock import Dock

_LOGGER = logging.getLogger(__name__)


class HTTPError(Exception):
    """Raised when an HTTP operation fails."""

    def __init__(self, status_code, message: str) -> None:
        """Raise HTTP Error."""
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class RemoteConnectionError(Exception):
    """Raised when HTTP connection fails."""


class ExternalSystemAlreadyRegistered(Exception):
    """Raised when the supplied external system is already registered"""


class TokenRegistrationError(Exception):
    """Raised when token registration fails"""


class IntegrationNotFound(Exception):
    """Supplied Integration is not found"""


class AuthenticationError(Exception):
    """Raised when HTTP login fails."""


class SystemCommandNotFound(Exception):
    """Raised when an invalid system command is supplied."""

    def __init__(self, message) -> None:
        """Raise command no found error."""
        self.message = message
        super().__init__(self.message)


class RemoteIsSleeping(ConnectionError):
    """Raised when the remote doesn't wake from sleep."""

    def __init__(self) -> None:
        """Raise remote is asleep"""
        self.message = "The remote is sleeping and was unable to be woken up"
        super().__init__(self.message)


class NoActivityRunning(Exception):
    """Raised when no activities are active."""

    def __init__(self) -> None:
        """Raise when no activities are active"""
        self.message = "No Activities are currently running"
        super().__init__(self.message)


class InvalidButtonCommand(Exception):
    """Raised when an invalid button command is supplied."""

    def __init__(self, message) -> None:
        """Raise command no found error."""
        self.message = message
        super().__init__(self.message)


class EntityCommandError(Exception):
    """Raised when an invalid entity command is supplied."""

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


class ApiKeyRevokeError(Exception):
    """Raised when failing to revoke existing api key"""


class ApiKeyCreateError(Exception):
    """Raised when unable to create api key"""


class DockNotFound(Exception):
    """Raised when unable to translate dock name"""


class RemoteGroup(list):
    """List of Unfolded Circle Remotes."""

    def __init__(self, *args) -> None:
        """Create list of UC Remotes."""
        super().__init__(args[0])


class Remote:
    """Unfolded Circle Remote Class."""

    def __init__(
        self, api_url, pin=None, apikey=None, wake_if_asleep: bool = True
    ) -> None:
        """Create a new UC Remote Object."""
        self.endpoint = self.validate_url(api_url)
        self.configuration_url = self.derive_configuration_url()
        self.apikey = apikey
        self.pin = pin
        self.activity_groups: list[ActivityGroup] = []
        self.activities: list[Activity] = []
        self._entities: list[UCMediaPlayerEntity] = []
        self._name = ""
        self._model_name = ""
        self._model_number = ""
        self._serial_number = ""
        self._hw_revision = ""
        self._manufacturer = "Unfolded Circle"
        self._mac_address = ""
        self._ip_address = ""
        self._hostname = ""
        self._battery_level = 0
        self._battery_status = ""
        self._is_charging = False
        self._ambient_light_intensity = 0
        self._display_auto_brightness = False
        self._display_brightness = 0
        self._button_backlight = False
        self._button_backlight_brightness = 0
        self._sound_effects = False
        self._sound_effects_volume = 0
        self._haptic_feedback = False
        self._display_timeout = 0
        self._wakeup_sensitivity = 0
        self._sleep_timeout = 0
        self._update_in_progress = False
        self._update_percent = 0
        self._download_percent = 0
        self._next_update_check_date = ""
        self._sw_version = ""
        self._check_for_updates = False
        self._automatic_updates = False
        self._available_update = []
        self._latest_sw_version = ""
        self._release_notes_url = ""
        self._release_notes = ""
        self._online = True
        self._memory_total = 0
        self._memory_available = 0
        self._storage_total = 0
        self._storage_available = 0
        self._cpu_load = {}
        self._cpu_load_one = 0.0
        self._power_mode = RemotePowerModes.NORMAL.value
        self._remotes = []
        self._ir_emitters = []
        self._ir_custom = []
        self._ir_codesets = []
        self._last_update_type = RemoteUpdateType.NONE
        self._is_simulator = None
        self._docks: list[Dock] = []
        self._wake_if_asleep = wake_if_asleep
        self._wake_on_lan: bool = False
        self._wake_on_lan_retries = 2
        self._wake_on_lan_available: bool = False
        self._external_entity_configuration_available: bool = False
        self._bt_enabled: bool = False
        self._wifi_enabled: bool = False
        self._new_web_configurator = True

    @property
    def name(self):
        """Name of the remote."""
        return self._name or "Unfolded Circle Remote Two"

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def memory_available(self):
        """Percentage of Memory used on the remote."""
        return int(round(self._memory_available, 0))

    @property
    def storage_available(self):
        """Percentage of Storage used on the remote."""
        return int(round(self._storage_available, 0))

    @property
    def sw_version(self):
        """Software Version."""
        return self._sw_version or "N/A"

    @property
    def model_name(self):
        """Model Name."""
        return self._model_name or "Remote Two"

    @property
    def model_number(self):
        """Model Number."""
        return self._model_number or "N/A"

    @property
    def serial_number(self):
        """Represents UC Remote Serial Number."""
        return self._serial_number or "N/A"

    @property
    def online(self):
        """Remote online state."""
        return self._online

    @property
    def is_charging(self):
        """Is Remote charging."""
        return self._is_charging

    @property
    def battery_level(self):
        """Integer percent of battery level remaining."""
        return self._battery_level

    @property
    def ambient_light_intensity(self):
        """Integer of lux."""
        return self._ambient_light_intensity

    @property
    def display_auto_brightness(self):
        """Boolean - Is auto brightness enabled"""
        return self._display_auto_brightness

    @property
    def display_brightness(self):
        """Display Brightness Level (0-100)"""
        return self._display_brightness

    @property
    def button_backlight(self):
        """Boolean - Is button backlight enabled"""
        return self._button_backlight

    @property
    def button_backlight_brightness(self):
        """Button Backlight Brightness Level (0-100)"""
        return self._button_backlight_brightness

    @property
    def sound_effects(self):
        """Boolean - Are sound effects enabled"""
        return self._sound_effects

    @property
    def sound_effects_volume(self):
        """Sound effect volume level (0-100)"""
        return self._sound_effects_volume

    @property
    def haptic_feedback(self):
        """Boolean - Are haptics enabled"""
        return self._haptic_feedback

    @property
    def display_timeout(self):
        """Display timeout in seconds (0-60)"""
        return self._display_timeout

    @property
    def wakeup_sensitivity(self):
        """Remote wake sensitivity level (0-3)"""
        return self._wakeup_sensitivity

    @property
    def sleep_timeout(self):
        """Remote sleep timeout in seconds (0-1800)"""
        return self._sleep_timeout

    @property
    def manufacturer(self):
        """Remote Manufacturer."""
        return self._manufacturer

    @property
    def hw_revision(self):
        """Remote Hardware Revision."""
        if self._hw_revision == "rev2":
            return "Revision 2"
        else:
            return self._hw_revision

    @property
    def battery_status(self):
        """Remote Battery Charging Status."""
        return self._battery_status

    @property
    def power_mode(self):
        """Remote Power Mode."""
        match self._power_mode:
            case RemotePowerModes.NORMAL.value:
                return "Normal"
            case RemotePowerModes.IDLE.value:
                return "Idle"
            case RemotePowerModes.LOW_POWER.value:
                return "Low Power"
            case RemotePowerModes.SUSPEND.value:
                return "Suspended"
            case _:
                return "Unknown"

    @property
    def update_in_progress(self):
        """Remote Update is in progress."""
        return self._update_in_progress

    @property
    def update_percent(self):
        """Remote Update percentage."""
        return self._update_percent

    @property
    def download_percent(self):
        """Remote download percentage."""
        return self._download_percent

    @property
    def next_update_check_date(self):
        """Remote Next Update Check Date."""
        return self._next_update_check_date

    @property
    def automatic_updates(self):
        """Does remote have automatic updates turned on."""
        return self._automatic_updates

    @property
    def check_for_updates(self):
        """Does remote automatically check for updates."""
        return self._check_for_updates

    @property
    def available_update(self):
        """List of available updates."""
        return self._available_update

    @property
    def latest_sw_version(self):
        """Latest software release version."""
        return self._latest_sw_version

    @property
    def release_notes_url(self):
        """Release notes url."""
        return self._release_notes_url

    @property
    def release_notes(self):
        """Release notes."""
        return self._release_notes

    @property
    def cpu_load(self):
        """CPU Load."""
        return self._cpu_load

    @property
    def cpu_load_one(self):
        """CPU Load 1 minute."""
        return self._cpu_load_one

    @property
    def mac_address(self):
        """MAC Address of Remote"""
        return self._mac_address

    @property
    def ip_address(self):
        """IP Address"""
        return self._ip_address

    @property
    def is_simulator(self):
        """Is the device a simulated remote"""
        return self._is_simulator

    @property
    def last_update_type(self) -> RemoteUpdateType:
        """Last update type from received message."""
        return self._last_update_type

    @property
    def wake_on_lan_retries(self):
        """The number of tries to connect after a WOL attempt"""
        return self._wake_on_lan_retries

    @wake_on_lan_retries.setter
    def wake_on_lan_retries(self, value):
        self._wake_on_lan_retries = value

    @property
    def wake_on_lan(self):
        """Is Wake on Lan Enabled"""
        return self._wake_on_lan

    @property
    def docks(self):
        """Return list of docks"""
        return self._docks

    @property
    def external_entity_configuration_available(self):
        """Is External entity configuration available"""
        return self._external_entity_configuration_available

    @property
    def new_web_configurator(self):
        """Is remote running new web configurator"""
        return self._new_web_configurator

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

    @staticmethod
    def name_from_model_id(model_id) -> str:
        """Returns the Remote Model name for a given model ID"""
        if model_id == "UCR2":
            return "Remote Two"
        return "Remote 3"

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
        if self.pin:
            auth = aiohttp.BasicAuth(AUTH_USERNAME, self.pin)
            return aiohttp.ClientSession(
                auth=auth, timeout=aiohttp.ClientTimeout(total=2)
            )

    async def validate_connection(self) -> bool:
        """Validate we can communicate with the remote given the supplied information."""
        async with (
            self.client() as session,
            session.head(self.url("activities")) as response,
        ):
            if response.status == 503:
                raise RemoteConnectionError
            if response.status == 401:
                raise AuthenticationError
            return response.status == 200

    async def wake(self, wait_for_confirmation: bool = True) -> bool:
        """Sends a magic packet to attempt to wake the device while asleep."""
        if self._is_simulator:
            return True

        send_magic_packet(self._mac_address)
        if wait_for_confirmation is False:
            return True
        attempt = 0
        while attempt < self._wake_on_lan_retries:
            try:
                if await self.validate_connection():
                    return True
            except Exception:
                pass
            attempt += 1
            await asyncio.sleep(1)
        return False

    async def raise_on_error(self, response):
        """Raise an HTTP error if the response returns poorly."""
        if not response.ok:
            content = await response.json()
            msg = f"{response.status} Request: {content['code']} Reason: {content['message']}"
            raise HTTPError(response.status, msg)
        return response

    ### Unfolded Circle API Keys ###
    async def get_api_keys(self) -> list[dict]:
        """Get all api Keys."""
        async with (
            self.client() as session,
            session.get(
                self.url("auth/api_keys"),
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def create_api_key(self) -> str:
        """Create api Key."""
        body = {"name": AUTH_APIKEY_NAME, "scopes": ["admin"]}

        async with (
            self.client() as session,
            session.post(self.url("auth/api_keys"), json=body) as response,
        ):
            await self.raise_on_error(response)
            api_info = await response.json()
            self.apikey = api_info["api_key"]
        return self.apikey

    async def revoke_api_key(self, key_name=AUTH_APIKEY_NAME):
        """Revokes api Key."""
        for key in await self.get_api_keys():
            if key["name"] == key_name:
                api_key_id = key["key_id"]
                break
        else:
            msg = f"API Key '{key_name}' not found."
            raise ApiKeyNotFound(key_name, msg)

        async with (
            self.client() as session,
            session.delete(self.url("auth/api_keys/" + api_key_id)) as response,
        ):
            await self.raise_on_error(response)

    async def create_api_key_revoke_if_exists(
        self, api_key_name=AUTH_APIKEY_NAME
    ) -> str:
        """Creates an API key and revokes any that presently exists"""
        try:
            for key in await self.get_api_keys():
                if key.get("name") == api_key_name:
                    await self.revoke_api_key()
        except Exception as ex:
            raise ApiKeyRevokeError from ex

        try:
            return await self.create_api_key()
        except Exception as ex:
            raise ApiKeyCreateError from ex

    async def get_registered_external_systems(self) -> dict:
        """Returns an array of dict[system,name] representing
        the registered external systems on the remote"""
        async with (
            self.client() as session,
            session.get(
                self.url("auth/external"),
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def get_registered_external_system(
        self,
        system: str,
    ) -> str:
        """Lists available token information for the given system"""

        if await self.is_external_system_valid(system):
            async with (
                self.client() as session,
                session.get(self.url(f"auth/external/{system}")) as response,
            ):
                await self.raise_on_error(response)
                return await response.json()
        raise ExternalSystemNotRegistered("Failed to get tokens from the remote")

    async def set_token_for_external_system(
        self,
        system: str,
        token_id: str,
        token: str,
        name: str = "Home Assistant Integration",
        description: str = None,
        url: str = None,
        data: str = None,
    ) -> str:
        """This method allows the external system to automatically provide the access
        token for the corresponding R2 integration instead of forcing the user to type it in.
        If the token name already exists for the given system, error 422 is returned."""

        if await self.is_external_system_valid(system):
            body = {
                "token_id": f"{token_id}",
                "name": f"{name}",
                "token": f"{token}",
            }
            if description:
                body["description"] = description
            if url:
                body["url"] = url
            if data:
                body["data"] = data
            async with (
                self.client() as session,
                session.post(
                    self.url(f"auth/external/{system}"), json=body
                ) as response,
            ):
                content = await response.json()
                if response.status == 422:
                    return await self.update_token_for_external_system(
                        system=system,
                        token_id=token_id,
                        token=token,
                        name=name,
                        description=description,
                        url=url,
                        data=data,
                    )
                if response.ok:
                    _LOGGER.debug(
                        "Token successfully registered to the remote %s", content
                    )
                    return content
                _LOGGER.error(
                    "Error while registering the new HA key to the remote %s", content
                )
                raise ExternalSystemNotRegistered(response)
        raise ExternalSystemNotRegistered("Failed to set token for the remote")

    async def update_token_for_external_system(
        self,
        system: str,
        token_id: str,
        token: str,
        name: str = "Home Assistant Integration",
        description: str = None,
        url: str = None,
        data: str = None,
    ) -> str:
        """This methods allows an already provided token of an external system to be updated.
        The token is identified by the system name and the token identification."""

        if await self.is_external_system_valid(system):
            body = {
                "token_id": f"{token_id}",
                "name": f"{name}",
                "token": f"{token}",
                "description": f"{description}",
                "url": f"{url}",
                "data": f"{data}",
            }
            async with (
                self.client() as session,
                session.put(
                    self.url(f"auth/external/{system}/{token_id}"), json=body
                ) as response,
            ):
                await self.raise_on_error(response)
                return await response.json()
        raise ExternalSystemNotRegistered("Failed to update token for the remote")

    async def delete_token_for_external_system(
        self,
        system: str,
        token_id: str,
    ) -> str:
        """Deletes supplied token for the given system."""

        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise ConnectionError

        if await self.is_external_system_valid(system):
            async with (
                self.client() as session,
                session.delete(
                    self.url(f"auth/external/{system}/{token_id}")
                ) as response,
            ):
                await self.raise_on_error(response)
                return await response.json()
        raise ExternalSystemNotRegistered("Failed to delete token from the remote")

    async def is_external_system_valid(self, system) -> bool:
        """Checks against the registered external systems on the remote
        to validate the supplied system name."""
        registered_systems = await self.get_registered_external_systems()
        _LOGGER.debug("Remote registered systems %s", registered_systems)
        for rs in registered_systems:
            if system == rs.get("system"):
                return True

    async def external_system_has_token(self, system) -> bool:
        """Checks against the external system on the remote
        to see if a token has been registered."""
        external_systems = await self.get_registered_external_system(system)

        for ext in external_systems:
            if ext.get("token_id") == "ws-ha-api":
                return True
        return False

    async def get_integrations(self) -> list[dict]:
        """Retrieves the list of integration instances."""
        async with self.client() as session:
            page = 1
            data: list[dict] = []
            while True:
                params = {"limit": 100, "page": page}
                response = await session.get(self.url("intg/instances"), params=params)
                await self.raise_on_error(response)
                count = int(response.headers.get("pagination-count", 0))
                data += await response.json()
                if len(data) >= count:
                    break
                page += 1
            return data

    async def put_integration(self, integration_id: str, command: str | None = None):
        """Update the given integration instance."""
        async with self.client() as session:
            if command:
                response = await session.put(
                    self.url(f"intg/instances/{integration_id}?cmd={command}")
                )
            else:
                response = await session.put(
                    self.url(f"intg/instances/{integration_id}")
                )
            await self.raise_on_error(response)
            return await response.json()

    async def get_driver_instance(self, driver_id: str) -> dict[str]:
        """Retrieves the driver instance from its driver id"""
        async with (
            self.client() as session,
            session.get(self.url(f"intg/drivers/{driver_id}")) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def create_driver_instance(self, driver_id: str, body: dict) -> str:
        """Retrieves the driver instance from its driver id"""
        async with (
            self.client() as session,
            session.post(self.url(f"intg/drivers/{driver_id}"), json=body) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def get_integration_instance_by_driver_id(self, driver_id: str) -> dict:
        """Returns driver information for a given integration instance ID"""
        remote_drivers_instances = await self.get_integrations()
        _LOGGER.debug("Remote list of integrations %s", remote_drivers_instances)
        try:
            ha_driver_instance = next(
                filter(
                    lambda instance: instance.get("driver_id", None) == driver_id,
                    remote_drivers_instances,
                )
            )
            return ha_driver_instance
        except StopIteration as ex:
            raise IntegrationNotFound from ex

    async def post_integration_setup(
        self, driver_id: str, reconfigure: bool, setup_data: dict
    ) -> dict:
        """POST to /intg/setup to start an integration driver setup"""
        body = {}
        if driver_id:
            body["driver_id"] = driver_id
        if reconfigure:
            body["reconfigure"] = reconfigure
        if setup_data:
            body["setup_data"] = setup_data
        body = {
            "driver_id": "hass",
            "reconfigure": False,
            "setup_data": {"expert": "false"},
        }
        async with (
            self.client() as session,
            session.post(self.url("intg/setup"), json=body) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def put_integration_setup(self, driver_id: str, input_values: dict) -> dict:
        """PUT to /intg/setup/:driver_id: to continue an integration driver setup"""
        body = {"input_values": input_values}
        async with (
            self.client() as session,
            session.put(self.url(f"intg/setup/{driver_id}"), json=body) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    @staticmethod
    async def get_version_information(base_url) -> dict[str]:
        """Get remote version information /pub/version"""
        headers = {
            "Accept": "application/json",
        }
        async with (
            aiohttp.ClientSession(
                headers=headers, timeout=aiohttp.ClientTimeout(total=5)
            ) as session,
            session.get(base_url + "/pub/version") as response,
        ):
            return await response.json()

    async def get_version(self) -> dict[str]:
        """Get remote version information /pub/version"""
        async with (
            self.client() as session,
            session.get(self.url("pub/version")) as response,
        ):
            information = await response.json()
            self._hostname = information.get("hostname", "")
            self._mac_address = information.get("address", "")

            if self._mac_address == "":  # We may be dealing with the simulator
                await self.get_remote_information()

            if self._is_simulator is True:
                # We only care about the beginning of the version for this compare
                self._external_entity_configuration_available = True
                self._new_web_configurator = False
            else:
                self._sw_version = information.get("os", "")
                if Version(self._sw_version) >= Version("2.0.0"):
                    self._external_entity_configuration_available = True
                if Version(self._sw_version) >= Version("2.2.0"):
                    self._new_web_configurator = True
                else:
                    self._new_web_configurator = False
            return information

    async def get_remote_wifi_info(self) -> dict[str, any]:
        """Get System wifi information from remote. address."""
        if self._is_simulator:
            self._mac_address = SIMULATOR_MAC_ADDRESS
            parsed_uri = urlparse(self.endpoint)
            self._ip_address = parsed_uri.netloc
            return {"ip_address": self._ip_address, "address": self._mac_address}
        async with (
            self.client() as session,
            session.get(self.url("system/wifi")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._mac_address = information.get("address")
            self._ip_address = information.get("ip_address")
            return information

    async def get_remote_information(self) -> str:
        """Get System information from remote. model_name,
        model_number, serial_number, hw_revision."""
        async with (
            self.client() as session,
            session.get(self.url("system")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._model_name = information.get("model_name")
            self._model_number = information.get("model_number")
            self._serial_number = information.get("serial_number")
            self._hw_revision = information.get("hw_revision")

            if self._model_name in SIMULATOR_NAMES:
                self._is_simulator = True
            return information

    async def get_remote_configuration(self) -> str:
        """Get System configuration from remote. User supplied remote name."""
        async with self.client() as session, session.get(self.url("cfg")) as response:
            await self.raise_on_error(response)
            information = await response.json()
            self._name = information.get("device").get("name")
            return information

    async def get_remote_drivers(self) -> list[dict[str, any]]:
        """List the integrations drivers on the remote."""
        async with (
            self.client() as session,
            session.get(self.url("intg/drivers")) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def start_driver_by_id(self, integration_id) -> list[dict[str, any]]:
        """Issue a command to the supplied integrations drivers on the remote."""
        async with (
            self.client() as session,
            session.put(
                self.url(f"intg/drivers/{integration_id}?cmd=START")
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def get_remote_integrations(self) -> list[dict[str, any]]:
        """List the integrations instances on the remote."""
        async with (
            self.client() as session,
            session.get(self.url("intg/instances")) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def get_remote_integration_entities(
        self, integration_id, reload=False
    ) -> list[dict[str, any]]:
        """Get the available entities of the given integration on the remote."""
        async with (
            self.client() as session,
            session.get(
                self.url(
                    f"intg/instances/{integration_id}/entities?reload=" + "true"
                    if reload
                    else "false"
                )
            ) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def set_remote_integration_entities(
        self, integration_id, entity_ids: list[dict[str, any]]
    ) -> bool:
        """Set the available entities of the given integration on the remote."""
        async with (
            self.client() as session,
            session.post(
                self.url(f"intg/instances/{integration_id}/entities"), json=entity_ids
            ) as response,
        ):
            await self.raise_on_error(response)
            return True

    async def delete_remote_entity(self, entity_id: str) -> bool:
        """Delete the given entity ID on the remote."""
        async with (
            self.client() as session,
            session.delete(self.url(f"entities/{entity_id}")) as response,
        ):
            await self.raise_on_error(response)
            return True

    async def get_remote_subscribed_entities(
        self, integration_id: str
    ) -> list[dict[str, any]]:
        """Return the list of subscribed entities for the given integration id."""
        async with (
            self.client() as session,
            session.get(self.url(f"entities?intg_ids={integration_id}")) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def add_remote_entities(self, integration_id, entity_ids: list[str]) -> bool:
        """Subscribe to the selected entities for the given integration id."""
        _LOGGER.debug("Add entities to remote %s : %s", self._ip_address, entity_ids)
        async with (
            self.client() as session,
            session.post(
                self.url(f"/intg/instances/{integration_id}/entities"), json=entity_ids
            ) as response,
        ):
            await self.raise_on_error(response)
            return True

    async def remove_remote_entities(self, entity_ids: list[str]) -> bool:
        """Remove the given subscribed entities."""
        _LOGGER.debug("Remove entities to remote %s : %s", self._ip_address, entity_ids)
        async with (
            self.client() as session,
            session.request(
                method="DELETE",
                url=self.url("/entities"),
                json={"entity_ids": entity_ids},
            ) as response,
        ):
            await self.raise_on_error(response)
            return True

    async def get_activities(self):
        """Return activities from Unfolded Circle Remote."""
        async with (
            self.client() as session,
            session.get(self.url("activities?limit=100")) as response,
        ):
            await self.raise_on_error(response)
            for activity in await response.json():
                new_activity = Activity(activity=activity, remote=self)
                self.activities.append(new_activity)
                response2 = await session.get(self.url("activities/" + new_activity.id))
                data = await response2.json()
                try:
                    self.update_activity_entities(
                        new_activity, data["options"]["included_entities"]
                    )
                except (KeyError, IndexError):
                    pass

                button_mapping = await session.get(
                    self.url("activities/" + new_activity.id + "/buttons")
                )

                for button in await button_mapping.json():
                    try:
                        short_press = button.get("short_press")
                    except Exception:
                        continue
                    match button.get("button"):
                        case "VOLUME_UP":
                            new_activity._volume_up_command = short_press
                        case "VOLUME_DOWN":
                            new_activity._volume_down_command = short_press
                        case "MUTE":
                            new_activity._volume_mute_command = short_press
                        case "PREV":
                            new_activity._prev_track_command = short_press
                        case "NEXT":
                            new_activity._next_track_command = short_press
                        case "PLAY":
                            new_activity._play_pause_command = short_press
                        case "POWER":
                            new_activity._power_command = short_press
                        case "STOP":  # Remote 3
                            new_activity._stop_command = short_press
                        case _:
                            pass
            return await response.json()

    async def get_activities_state(self):
        """Get activity state for all activities."""
        async with (
            self.client() as session,
            session.get(self.url("activities")) as response,
        ):
            await self.raise_on_error(response)
            updated_activities = await response.json()
            for updated_activity in updated_activities:
                for activity in self.activities:
                    if activity._id == updated_activity["entity_id"]:
                        activity._state = updated_activity["attributes"]["state"]

    async def get_activity_groups(self) -> json:
        """Return activity groups with the list of activity IDs from Unfolded Circle Remote."""
        async with (
            self.client() as session,
            session.get(self.url("activity_groups?limit=100")) as response,
        ):
            await self.raise_on_error(response)
            self.activity_groups = []
            for activity_group_data in await response.json():
                # _LOGGER.debug("get_activity_groups %s", json.dumps(activity_group_data, indent=2))
                name = "DEFAULT"
                if activity_group_data.get("name", None) and isinstance(
                    activity_group_data.get("name", None), dict
                ):
                    name = next(iter(activity_group_data.get("name").values()))
                activity_group = ActivityGroup(
                    group_id=activity_group_data.get("group_id"),
                    name=name,
                    remote=self,
                    state=activity_group_data.get("state"),
                )
                response2 = await session.get(
                    self.url("activity_groups/" + activity_group_data.get("group_id"))
                )
                await self.raise_on_error(response2)
                activity_group_definition = await response2.json()
                for activity in activity_group_definition.get("activities"):
                    for local_activity in self.activities:
                        if local_activity._id == activity.get("entity_id"):
                            activity_group.activities.append(local_activity)
                await response2.json()
                self.activity_groups.append(activity_group)
            return await response.json()

    async def get_remote_battery_information(self) -> json:
        """Get Battery information from remote. battery_level, battery_status, is_charging."""
        async with (
            self.client() as session,
            session.get(self.url("system/power/battery")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._battery_level = information["capacity"]
            self._battery_status = information["status"]
            self._is_charging = information["power_supply"]
            return information

    async def get_stats(self) -> json:
        """Get usage stats from the remote."""
        async with (
            self.client() as session,
            session.get(self.url("pub/status")) as response,
        ):
            await self.raise_on_error(response)
            status = await response.json()
            self._memory_total = status.get("memory").get("total_memory") / 1048576
            self._memory_available = (
                status.get("memory").get("available_memory") / 1048576
            )

            self._storage_total = (
                status.get("filesystem").get("user_data").get("used")
                + status.get("filesystem").get("user_data").get("available") / 1048576
            )
            self._storage_available = (
                status.get("filesystem").get("user_data").get("available") / 1048576
            )

            self._cpu_load = status.get("load_avg")
            self._cpu_load_one = status.get("load_avg").get("one")
            return status

    async def get_remote_ambient_light_information(self) -> int:
        """Get Remote Ambient Light Level. ambient_light_intensity."""
        async with (
            self.client() as session,
            session.get(self.url("system/sensors/ambient_light")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._ambient_light_intensity = information["intensity"]
            return self._ambient_light_intensity

    async def get_remote_display_settings(self) -> str:
        """Get remote display settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/display")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._display_auto_brightness = settings.get("auto_brightness")
            self._display_brightness = settings.get("brightness")
            return settings

    async def patch_remote_display_settings(
        self, auto_brightness=None, brightness=None
    ) -> bool:
        """Update remote display settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise ConnectionError

        display_settings = await self.get_remote_display_settings()
        if auto_brightness is not None:
            display_settings["auto_brightness"] = auto_brightness
        if brightness is not None:
            display_settings["brightness"] = brightness

        async with (
            self.client() as session,
            session.patch(self.url("cfg/display"), json=display_settings) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def get_remote_button_settings(self) -> str:
        """Get remote button settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/button")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._button_backlight = settings.get("auto_brightness")
            self._button_backlight_brightness = settings.get("brightness")
            return settings

    async def patch_remote_button_settings(
        self, auto_brightness=None, brightness=None
    ) -> bool:
        """Update remote button settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        button_settings = await self.get_remote_button_settings()
        if auto_brightness is not None:
            button_settings["auto_brightness"] = auto_brightness
        if brightness is not None:
            button_settings["brightness"] = brightness

        async with (
            self.client() as session,
            session.patch(self.url("cfg/button"), json=button_settings) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def get_remote_sound_settings(self) -> str:
        """Get remote sound settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/sound")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._sound_effects = settings.get("enabled")
            self._sound_effects_volume = settings.get("volume")
            return settings

    async def patch_remote_sound_settings(
        self, sound_effects=None, sound_effects_volume=None
    ) -> bool:
        """Update remote sound settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        sound_settings = await self.get_remote_sound_settings()
        if sound_effects is not None:
            sound_settings["enabled"] = sound_effects
        if sound_effects_volume is not None:
            sound_settings["volume"] = sound_effects_volume

        async with (
            self.client() as session,
            session.patch(self.url("cfg/sound"), json=sound_settings) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def get_remote_haptic_settings(self) -> str:
        """Get remote haptic settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/haptic")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._haptic_feedback = settings.get("enabled")
            return settings

    async def patch_remote_haptic_settings(self, haptic_feedback=None) -> bool:
        """Update remote haptic settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        haptic_settings = await self.get_remote_haptic_settings()
        if haptic_feedback is not None:
            haptic_settings["enabled"] = haptic_feedback

        async with (
            self.client() as session,
            session.patch(self.url("cfg/haptic"), json=haptic_settings) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def get_remote_power_saving_settings(self) -> str:
        """Get remote power saving settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/power_saving")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._display_timeout = settings.get("display_off_sec")
            self._wakeup_sensitivity = settings.get("wakeup_sensitivity")
            self._sleep_timeout = settings.get("standby_sec")
            return settings

    async def patch_remote_power_saving_settings(
        self, display_timeout=None, wakeup_sensitivity=None, sleep_timeout=None
    ) -> bool:
        """Update remote power saving settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        power_saving_settings = await self.get_remote_power_saving_settings()
        if display_timeout is not None:
            power_saving_settings["display_off_sec"] = display_timeout
        if wakeup_sensitivity is not None:
            power_saving_settings["wakeup_sensitivity"] = wakeup_sensitivity
        if sleep_timeout is not None:
            power_saving_settings["standby_sec"] = sleep_timeout

        async with (
            self.client() as session,
            session.patch(
                self.url("cfg/power_saving"), json=power_saving_settings
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def get_remote_update_settings(self) -> str:
        """Get remote update settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/software_update")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()
            self._check_for_updates = settings.get("check_for_updates")
            self._automatic_updates = settings.get("auto_update")
            return settings

    async def get_remote_update_information(self) -> bool:
        """Get remote update information."""
        if self._is_simulator:
            return
        async with (
            self.client() as session,
            session.get(self.url("system/update")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._update_in_progress = information["update_in_progress"]
            self._sw_version = information["installed_version"]
            download_status = ""
            if "available" in information:
                self._available_update = information["available"]
                for update in self._available_update:
                    if update.get("channel") in ["STABLE", "TESTING"]:
                        if (
                            self._latest_sw_version == ""
                            or self._latest_sw_version < update.get("version")
                        ):
                            self._release_notes_url = update.get("release_notes_url")
                            self._latest_sw_version = update.get("version")
                            self._release_notes = update.get("description").get("en")
                            download_status = update.get("download")
                    else:
                        self._latest_sw_version = self._sw_version
            else:
                self._latest_sw_version = self._sw_version

            if download_status in ("PENDING", "ERROR"):
                try:
                    # When download status is pending, the first request to system/update
                    # will request the download of the latest firmware but will not install
                    response = await self.update_remote(download_only=True)
                except HTTPError:
                    pass
                return information

    async def get_remote_force_update_information(self) -> bool:
        """Force a remote firmware update check."""
        async with (
            self.client() as session,
            session.put(self.url("system/update")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._update_in_progress = information["update_in_progress"]
            self._sw_version = information["installed_version"]
            download_status = ""
            if "available" in information:
                self._available_update = information["available"]
                for update in self._available_update:
                    if update.get("channel") in ["STABLE", "TESTING"]:
                        if (
                            self._latest_sw_version == ""
                            or self._latest_sw_version < update.get("version")
                        ):
                            self._release_notes_url = update.get("release_notes_url")
                            self._latest_sw_version = update.get("version")
                            self._release_notes = update.get("description").get("en")
                            download_status = update.get("download")
                    else:
                        self._latest_sw_version = self._sw_version
            else:
                self._latest_sw_version = self._sw_version

            if download_status in ("PENDING", "ERROR"):
                try:
                    # When download status is pending, the first request to system/update
                    # will request the download of the latest firmware but will not install
                    response = await self.update_remote(download_only=True)
                except HTTPError:
                    pass
            return information

    async def get_remote_network_settings(self) -> str:
        """Get remote network settings"""
        async with (
            self.client() as session,
            session.get(self.url("cfg/network")) as response,
        ):
            await self.raise_on_error(response)
            settings = await response.json()

            self._bt_enabled = settings.get("bt_enabled")
            self._wifi_enabled = settings.get("wifi_enabled")

            try:
                if self._model_number.upper() == "UCR3":
                    self._wake_on_lan = False
                    self._wake_on_lan_available = False
                else:
                    self._wake_on_lan = settings.get("wake_on_wlan").get("enabled")
                    self._wake_on_lan_available = True
            except AttributeError:
                self._wake_on_lan = False
            return settings

    async def patch_remote_network_settings(
        self,
        bt_enabled: bool = None,
        wifi_enabled: bool = None,
        wake_on_lan: bool = None,
    ) -> bool:
        """Update remote network settings"""
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        network_settings = await self.get_remote_network_settings()
        if bt_enabled is not None:
            network_settings["bt_enabled"] = bt_enabled
        if wifi_enabled is not None:
            network_settings["wifi_enabled"] = wifi_enabled
        if wake_on_lan is not None and Version(self._sw_version) >= Version("2.0.0"):
            network_settings["wake_on_wlan"]["enabled"] = wake_on_lan

        async with (
            self.client() as session,
            session.patch(self.url("cfg/network"), json=network_settings) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return True

    async def update_remote(self, download_only: bool = False) -> str:
        """Update Remote."""
        # If we only want to download the firmware, check the status.
        # If it's not pending or error, bail so we don't accidentally
        # invoke an install
        if download_only is True:
            download_status = await self.get_update_status()
            if download_status.get("state") not in ("PENDING", "ERROR"):
                return

        async with (
            self.client() as session,
            session.post(self.url("system/update/latest")) as response,
        ):
            if response.ok:
                information = await response.json()
                if information.get("state") in ["DOWNLOAD", "DOWNLOADED"]:
                    self._update_in_progress = False

                if information.get("state") == "START":
                    self._update_in_progress = True
            if response.status == 409:
                information = {"state": "DOWNLOADING"}
            if response.status == 503:
                information = {"state": "NO_BATTERY"}
            return information

    async def get_update_status(self) -> str:
        """Update remote status."""
        # WIP: Gets Update Status -- Only supports latest."
        async with (
            self.client() as session,
            session.get(self.url("system/update/latest")) as response,
        ):
            information = await response.json()
            if response.ok:
                return information
            return {"state": "UNKNOWN"}

    async def get_activity_state(self, entity_id) -> str:
        """Get activity state for a remote entity."""
        async with (
            self.client() as session,
            session.get(self.url("activities")) as response,
        ):
            await self.raise_on_error(response)
            current_activities = await response.json()
            for current_activity in current_activities:
                if entity_id == current_activity["entity_id"]:
                    return current_activity["attributes"]["state"]

    async def get_activity(self, entity_id) -> any:
        """Get activity state for a remote entity."""
        async with (
            self.client() as session,
            session.get(self.url("activities/" + entity_id)) as response,
        ):
            await self.raise_on_error(response)
            return await response.json()

    async def post_system_command(self, cmd) -> str:
        """POST a system command to the remote."""
        if cmd in SYSTEM_COMMANDS:
            if self._wake_if_asleep and self._wake_on_lan:
                if not await self.wake():
                    raise RemoteIsSleeping

            async with (
                self.client() as session,
                session.post(self.url("system?cmd=" + cmd)) as response,
            ):
                await self.raise_on_error(response)
                response = await response.json()
                return response
        else:
            raise SystemCommandNotFound("Invalid System Command Supplied")

    async def get_remotes(self) -> list:
        """Get list of remotes defined. (IR Remotes as defined by Unfolded Circle)."""
        remote_data = {}

        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        async with (
            self.client() as session,
            session.get(self.url("remotes")) as response,
        ):
            await self.raise_on_error(response)
            remotes = await response.json()
            for remote in remotes:
                # integration_id == uc.main : bug with web configurator
                if remote.get("enabled") is True and remote.get(
                    "integration_id"
                ).startswith("uc.main"):
                    remote_data = {
                        "name": remote.get("name").get("en"),
                        "entity_id": remote.get("entity_id"),
                    }
                    self._remotes.append(remote_data.copy())
            return self._remotes

    async def get_custom_codesets(self) -> list:
        """Get list of IR code sets defined."""
        ir_data = {}
        async with (
            self.client() as session,
            session.get(self.url("ir/codes/custom")) as response,
        ):
            await self.raise_on_error(response)
            code_sets = await response.json()
            for ir in code_sets:
                ir_data = {
                    "device": ir.get("device"),
                    "device_id": ir.get("device_id"),
                }
                self._ir_custom.append(ir_data.copy())
            return self._ir_custom

    async def get_remote_codesets(self) -> list:
        """Get list of remote codesets."""
        ir_data = {}
        if not self._remotes:
            await self.get_remotes()
        for remote in self._remotes:
            async with (
                self.client() as session,
                session.get(
                    self.url("remotes/" + remote.get("entity_id") + "/ir")
                ) as response,
            ):
                await self.raise_on_error(response)
                code_set = await response.json()
                ir_data = {
                    "name": remote.get("name"),
                    "device_id": code_set.get("id"),
                }
                self._ir_codesets.append(ir_data.copy())
        return self._ir_codesets

    async def get_docks(self) -> list:
        """Get list of docks defined."""
        async with (
            self.client() as session,
            session.get(self.url("docks")) as response,
        ):
            await self.raise_on_error(response)
            docks = await response.json()
            for info in docks:
                dock = Dock(
                    dock_id=info.get("dock_id"),
                    remote_endpoint=self.endpoint,
                    apikey=self.apikey,
                    name=info.get("name"),
                    ws_url=info.get("resolved_ws_url"),
                    is_active=info.get("active"),
                    model_name=info.get("model"),
                    hardware_revision=info.get("revision"),
                    serial_number=info.get("serial"),
                    led_brightness=info.get("led_brightness"),
                    ethernet_led_brightness=info.get("eth_led_brightness"),
                    software_version=info.get("version"),
                    state=info.get("state"),
                    is_learning_active=info.get("learning_active"),
                    remote_configuration_url=self.configuration_url,
                )
                self._docks.append(dock)
            return self._docks

    def get_dock_by_id(self, dock_id: str) -> Dock:
        for dock in self._docks:
            if dock.id == dock_id:
                return dock

    async def get_ir_emitters(self) -> list:
        """Get list of docks defined."""
        dock_data = {}
        async with (
            self.client() as session,
            session.get(self.url("ir/emitters")) as response,
        ):
            await self.raise_on_error(response)
            docks = await response.json()
            for dock in docks:
                if dock.get("active") is True:
                    dock_data = {
                        "name": dock.get("name"),
                        "device_id": dock.get("device_id"),
                    }
                    self._ir_emitters.append(dock_data.copy())
            return self._ir_emitters

    async def send_button_command(self, command="", repeat=0, **kwargs) -> bool:
        """Send a predefined button command to the remote kwargs: activity, hold."""
        activity_id = None
        hold = kwargs.get("hold", False)
        activity = kwargs.get("activity", None)
        delay_secs = kwargs.get("delay_secs", 0)
        repeat = kwargs.get("repeat", 1)

        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        if activity:
            for act in self.activities:
                if act.name == activity:
                    activity_id = act.id
        else:
            for act in self.activities:
                if act.is_on():
                    activity_id = act.id
                    continue

        if not activity_id:
            raise NoActivityRunning

        try:
            entity_id, cmd_id, params = await self.get_physical_button_mapping(
                activity_id, command.upper(), hold
            )
        except HTTPError as ex:
            raise InvalidButtonCommand(ex.message) from ex

        try:
            for _ in range(repeat):
                if delay_secs and delay_secs > 0:
                    await asyncio.sleep(delay_secs)
                success = await self.execute_entity_command(entity_id, cmd_id, params)
                if not success:
                    return False
        except HTTPError as ex:
            raise EntityCommandError(ex.message) from ex

    async def get_physical_button_mapping(self, activity_id, button_id, hold) -> str:
        """Get the physical button mapping for the given activity."""
        async with (
            self.client() as session,
            session.get(
                self.url(f"activities/{activity_id}/buttons/{button_id}")
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()

            if hold:
                action = response.get("long_press")
            else:
                action = response.get("short_press")

            entity_id = action.get("entity_id")
            cmd_id = action.get("cmd_id")
            params = action.get("params")
            return entity_id, cmd_id, params

    async def execute_entity_command(self, entity_id, cmd_id, params=None) -> bool:
        """Execute a command on a remote entity."""
        body = {"entity_id": entity_id, "cmd_id": cmd_id}
        if params:
            body["params"] = params
        async with (
            self.client() as session,
            session.put(
                self.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self.raise_on_error(response)
            return response.status == 200

    async def send_remote_command(
        self, device="", command="", repeat=0, codeset="", **kwargs
    ) -> bool:
        """Send a remote command to the dock kwargs: code,format,dock,port."""
        body_port = {}
        body_repeat = {}
        codeset_id = ""

        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        if "code" in kwargs and "format" in kwargs:
            # Send an IR command (HEX/PRONTO)
            body = {"code": kwargs.get("code"), "format": kwargs.get("format")}
        if device != "" and command != "":
            # Send a predefined code
            ir_code = next(
                (code for code in self._ir_codesets if code.get("name") == device),
                None,
            )
            if ir_code:
                codeset_id = ir_code.get("device_id")
            # Check if user sent in a delivered code
            if not codeset_id != "" and codeset != "":
                manufacturers: list = await self.get_ir_manufacturers(device)
                for manufacturer in manufacturers:
                    codesets = await self.get_ir_manufacturer_codesets(
                        manufacturer.get("id")
                    )
                    for cs in codesets:
                        if cs.get("name") == codeset:
                            codeset_id = cs.get("id")

            if codeset_id == "":
                raise InvalidIRFormat("No predefined code found")

            body = {"codeset_id": codeset_id, "cmd_id": command}
        else:
            raise InvalidIRFormat("Supply (code and format) or (device and command)")

        if repeat > 0:
            body_repeat = {"repeat": repeat}

        if "port" in kwargs:
            body_port = {"port_id": kwargs.get("port")}

        if "dock" in kwargs:
            dock_name: str = kwargs.get("dock")
            emitter = next(
                (
                    dock
                    for dock in self._ir_emitters
                    if dock.get("name", "").lower() == dock_name.lower()
                ),
                None,
            )
            emitter_id = emitter.get("device_id")
        else:
            emitter_id = self._ir_emitters[0].get("device_id")

        if emitter_id is None:
            raise NoEmitterFound("No emitter could be found with the supplied criteria")

        body_merged = {**body, **body_repeat, **body_port}

        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        async with (
            self.client() as session,
            session.put(
                self.url("ir/emitters/" + emitter_id + "/send"), json=body_merged
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return response == 200

    async def get_ir_manufacturers(self, manufacturer: str) -> dict[str, str]:
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        async with (
            self.client() as session,
            session.get(
                self.url(f"ir/codes/manufacturers?page=1&limit=100&q={manufacturer}"),
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return response

    async def get_ir_manufacturer_codesets(
        self, manufacturer_id: str
    ) -> dict[str, str]:
        if self._wake_if_asleep and self._wake_on_lan:
            if not await self.wake():
                raise RemoteIsSleeping

        async with (
            self.client() as session,
            session.get(
                self.url(f"ir/codes/manufacturers/{manufacturer_id}?page=1&limit=100"),
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return response

    def update_from_message(self, message: any) -> None:
        """Update internal data from received websocket messages
        data instead of polling the remote"""
        data = json.loads(message)
        # _LOGGER.debug("RC2 received websocket message %s",data)
        try:
            # Beware when modifying this code : if an attribute is missing in one of the if clauses,
            # it will raise an exception and skip the other if clauses
            # TODO Missing software updates (message format ?)
            if data["msg"] == "ambient_light":
                _LOGGER.debug("Unfolded circle remote update light")
                self._ambient_light_intensity = data["msg_data"]["intensity"]
                self._last_update_type = RemoteUpdateType.AMBIENT_LIGHT
                return
            if data["msg"] == "battery_status":
                _LOGGER.debug("Unfolded circle remote update battery")
                self._battery_status = data["msg_data"]["status"]
                self._battery_level = data["msg_data"]["capacity"]
                self._is_charging = data["msg_data"]["power_supply"]
                self._last_update_type = RemoteUpdateType.BATTERY
                return
            if data["msg"] == "software_update":
                _LOGGER.debug("Unfolded circle remote software update")
                total_steps = 0
                update_state = "INITIAL"
                current_step = 0
                percentage_offset = 0
                if data.get("msg_data").get("event_type") == "START":
                    self._update_in_progress = True
                if data.get("msg_data").get("event_type") == "PROGRESS":
                    # progress dict
                    progress = data.get("msg_data").get("progress")
                    update_state = progress.get("state")
                    current_step = progress.get("current_step")
                    total_steps = progress.get("total_steps")
                    if total_steps:
                        # Amount to add to total percent for multiple steps
                        offset = round(100 / total_steps)
                        # The offset as a percent to adjust step percentage by
                        percentage_offset = offset / 100
                    match update_state:
                        case "START":
                            self._update_percent = 0
                        case "RUN":
                            current_step = progress.get("current_step")
                            self._update_percent = 0
                        case "PROGRESS":
                            step_offset = offset * (current_step - 1)
                            self._update_percent = (
                                percentage_offset * progress.get("current_percent")
                            ) + step_offset
                        case "SUCCESS":
                            self._update_percent = 100
                            self._sw_version = self.latest_sw_version
                        case "DONE":
                            self._update_in_progress = False
                            self._update_percent = 0
                            self._download_percent = 0
                            self._sw_version = self.latest_sw_version
                        case "DOWNLOAD":
                            self._download_percent = progress.get("download_percent")
                        case _:
                            self._update_in_progress = False
                            self._update_percent = 0

                self._last_update_type = RemoteUpdateType.SOFTWARE
                return
            if data["msg"] == "configuration_change":
                _LOGGER.debug("Unfolded circle configuration change")
                state = data.get("msg_data").get("new_state")
                if state.get("display") is not None:
                    self._display_auto_brightness = state.get("display").get(
                        "auto_brightness"
                    )
                    self._display_brightness = state.get("display").get("brightness")
                if state.get("button") is not None:
                    self._button_backlight = state.get("button").get("auto_brightness")
                    self._button_backlight_brightness = state.get("button").get(
                        "brightness"
                    )
                if state.get("sound") is not None:
                    self._sound_effects = state.get("sound").get("enabled")
                    self._sound_effects_volume = state.get("sound").get("volume")
                if state.get("haptic") is not None:
                    self._haptic_feedback = state.get("haptic").get("enabled")
                if state.get("software_update") is not None:
                    self._check_for_updates = state.get("software_update").get(
                        "check_for_updates"
                    )
                    self._automatic_updates = state.get("software_update").get(
                        "auto_update"
                    )
                if state.get("power_saving") is not None:
                    self._display_timeout = state.get("power_saving").get(
                        "display_off_sec"
                    )
                    self._wakeup_sensitivity = state.get("power_saving").get(
                        "wakeup_sensitivity"
                    )
                    self._sleep_timeout = state.get("power_saving").get("standby_sec")
                if state.get("network") is not None:
                    self._wake_on_lan = (
                        state.get("network").get("wake_on_wlan").get("enabled")
                    )
                self._last_update_type = RemoteUpdateType.CONFIGURATION
            if data["msg"] == "power_mode_change":
                _LOGGER.debug("Unfolded circle Power Mode change")
                self._power_mode = data.get("msg_data").get("mode")
                self._last_update_type = RemoteUpdateType.CONFIGURATION
        except (KeyError, IndexError):
            pass
        try:
            # Extract media player entities for future use
            if (
                data["msg_data"]["entity_type"] == "media_player"
                and data["msg_data"]["new_state"]["attributes"]
            ):
                attributes = data["msg_data"]["new_state"]["attributes"]
                entity_id = data["msg_data"]["entity_id"]
                entity: UCMediaPlayerEntity = self.get_entity(entity_id)
                entity.update_attributes(attributes)
                self._last_update_type = RemoteUpdateType.ACTIVITY
        except (KeyError, IndexError) as ex:
            _LOGGER.debug(
                "Unfolded circle remote update error while reading data: %s %s",
                data,
                ex,
            )
            pass
        try:
            # Only message where we have the link between the new activity and the media player entities (one message per media player entity)
            # We don't want to extract all media player entities by API one by one so we get them dynamically through websockets
            # and this is the only message here that gives the link activity -> entities
            # TODO : not sure this will happen like that all the time :
            #  ["msg_data"]["new_state"]["attributes"]["step"]["command"] = { "cmd_id": "media_player.on", "entity_id": "<media player entity id>"...}
            if (
                data["msg_data"]["entity_type"] == "activity"
                and data["msg_data"]["new_state"]["attributes"]["state"] == "RUNNING"
                and data["msg_data"]["new_state"]["attributes"]["step"]["entity"][
                    "type"
                ]
                == "media_player"
                and data["msg_data"]["new_state"]["attributes"]["step"]["command"][
                    "cmd_id"
                ]
                == "media_player.on"
            ):
                _LOGGER.debug(
                    "Unfolded circle remote update link between activity and entities"
                )
                activity_id = data["msg_data"]["entity_id"]
                entity_id = data["msg_data"]["new_state"]["attributes"]["step"][
                    "command"
                ]["entity_id"]
                entity_data = data["msg_data"]["new_state"]["attributes"]["step"][
                    "entity"
                ]
                entity_data["entity_id"] = entity_id
                for activity in self.activities:
                    if activity._id == activity_id:
                        self.update_activity_entities(activity, [entity_data])
                self._last_update_type = RemoteUpdateType.ACTIVITY
        except (KeyError, IndexError):
            pass
        try:
            # Activity On or Off
            if data["msg_data"]["entity_type"] == "activity" and (
                data["msg_data"]["new_state"]["attributes"]["state"] == "ON"
                or data["msg_data"]["new_state"]["attributes"]["state"] == "OFF"
            ):
                _LOGGER.debug("Unfolded circle remote update activity")
                new_state = data["msg_data"]["new_state"]["attributes"]["state"]
                activity_id = data["msg_data"]["entity_id"]

                for activity in self.activities:
                    if activity._id == activity_id:
                        activity._state = new_state
                        # Check after included entities in activity
                        if data["msg_data"]["new_state"].get("options") and data[
                            "msg_data"
                        ]["new_state"]["options"].get("included_entities"):
                            included_entities = data["msg_data"]["new_state"][
                                "options"
                            ]["included_entities"]
                            self.update_activity_entities(activity, included_entities)

                for activity_group in self.activity_groups:
                    if activity_group.is_activity_in_group(activity_id):
                        group_state = "OFF"
                        for activity in self.activities:
                            if (
                                activity_group.is_activity_in_group(activity._id)
                                and activity.is_on()
                            ):
                                group_state = "ON"
                                break
                        activity_group._state = group_state
                self._last_update_type = RemoteUpdateType.ACTIVITY
        except (KeyError, IndexError):
            pass

    def get_entity(self, entity_id) -> any:
        for entity in self._entities:
            if entity._id == entity_id:
                return entity
        entity = UCMediaPlayerEntity(entity_id, self)
        self._entities.append(entity)
        return entity

    async def get_entity_data(self, entity_id) -> any:
        """Update remote status."""
        async with (
            self.client() as session,
            session.get(self.url("entities/" + entity_id)) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            return information

    def update_activity_entities(self, activity, included_entities: any):
        _LOGGER.debug(
            "Unfolded circle remote update_activity_entities %s %s",
            activity.name,
            included_entities,
        )
        for included_entity in included_entities:
            entity_type = included_entity.get("entity_type", None)
            if entity_type is None:
                entity_type = included_entity.get("type", None)
            if entity_type != "media_player":
                continue
            entity: UCMediaPlayerEntity = self.get_entity(included_entity["entity_id"])
            entity._activity = activity
            if included_entity.get("name", None) is not None:
                entity._name = next(iter(included_entity["name"].values()))
            if included_entity.get("entity_commands", None) is not None:
                entity._entity_commands = included_entity["entity_commands"]
            activity.add_mediaplayer_entity(entity)

    def get_activity_by_id(self, activity_id):
        for activity in self.activities:
            if activity_id == activity.id:
                return activity

    async def init(self):
        """Retrieves all information about the remote."""
        _LOGGER.debug("Unfolded circle remote init data")
        tasks = [
            self.get_remote_battery_information(),
            self.get_remote_ambient_light_information(),
            self.get_remote_update_information(),
            self.get_remote_configuration(),
            self.get_remote_information(),
            self.get_stats(),
            self.get_remote_display_settings(),
            self.get_remote_button_settings(),
            self.get_remote_sound_settings(),
            self.get_remote_haptic_settings(),
            self.get_remote_power_saving_settings(),
            self.get_remote_update_settings(),
            self.get_remote_network_settings(),
            self.get_activities(),
            self.get_remote_codesets(),
            self.get_ir_emitters(),
            self.get_remote_wifi_info(),
            self.get_docks(),
            self.get_version(),
        ]
        for coroutine in asyncio.as_completed(tasks):
            try:
                await coroutine
            except Exception as ex:
                _LOGGER.error("Unfolded circle remote initialization error %s", ex)

        try:
            await self.get_activity_groups()
            for activity_group in self.activity_groups:
                await activity_group.update()
        except Exception as ex:
            _LOGGER.error("Unfolded circle remote initialization error %s", ex)

        _LOGGER.debug("Unfolded circle remote data initialized")

    async def update(self):
        """Updates all information about the remote."""
        _LOGGER.debug("Unfolded circle remote update data")
        tasks = [
            self.get_remote_battery_information(),
            self.get_remote_ambient_light_information(),
            self.get_remote_update_information(),
            self.get_remote_configuration(),
            self.get_remote_information(),
            self.get_stats(),
            self.get_remote_display_settings(),
            self.get_remote_button_settings(),
            self.get_remote_sound_settings(),
            self.get_remote_haptic_settings(),
            self.get_remote_power_saving_settings(),
            self.get_remote_update_settings(),
            self.get_remote_network_settings(),
            self.get_activities_state(),
        ]
        for coroutine in asyncio.as_completed(tasks):
            try:
                await coroutine
            except Exception as ex:
                _LOGGER.debug("Unfolded circle remote update error %s", ex)

        for activity_group in self.activity_groups:
            try:
                await activity_group.update()
            except Exception as ex:
                _LOGGER.debug("Unfolded circle remote update error %s", ex)
        _LOGGER.debug("Unfolded circle remote data updated")

    async def polling_update(self):
        """Updates only polled information from the remote."""
        _LOGGER.debug("Unfolded circle remote update data")
        group = asyncio.gather(self.get_stats())
        await group


class UCMediaPlayerEntity:
    """Internal class to track the media player entities reported by the remote"""

    def __init__(self, entity_id: str, remote: Remote) -> None:
        self._id = entity_id
        self._activity = Activity
        self._remote = remote
        self._state = "OFF"
        self._name = entity_id
        self._type = "media_player"
        self._source_list = []
        self._current_source = ""
        self._media_title = ""
        self._media_artist = ""
        self._media_album = ""
        self._media_type = ""
        self._media_duration = 0
        self._media_position = 0
        self._media_position_updated_at: datetime = None
        self._muted = False
        self._volume = 0.0
        self._media_image_url = None
        self._entity_commands: list[str] = []
        self._initialized = False

    async def update_data(self, force=False):
        """Update entity data from remote"""
        _LOGGER.debug("RC2 update media player entity from remote %s", self.name)
        if self._initialized and not force:
            return
        data = await self._remote.get_entity_data(self._id)
        self.update_attributes(data["attributes"])
        self._initialized = True

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def available_commands(self) -> list[str]:
        return self._entity_commands

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def activity(self):
        return self._activity

    @property
    def state(self) -> str:
        return self._state

    @property
    def source_list(self) -> list[str]:
        return self._source_list

    @property
    def current_source(self) -> str:
        return self._current_source

    @property
    def media_image_url(self) -> str:
        return self._media_image_url

    @property
    def media_title(self) -> str:
        return self._media_title

    @property
    def media_artist(self) -> str:
        return self._media_artist

    @property
    def media_album(self) -> str:
        return self._media_album

    @property
    def media_type(self) -> str:
        return self._media_type

    @property
    def media_duration(self) -> int:
        return self._media_duration

    @property
    def media_position(self) -> int:
        return self._media_position

    @property
    def media_position_updated_at(self):
        """Last time status was updated."""
        return self._media_position_updated_at

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_on(self) -> bool:
        if self._state != "OFF":
            return True
        return False

    def update_attributes(self, attributes: any) -> dict[str, any]:
        attributes_changed = {"entity_id": self._id, "name": self.name}
        if attributes.get("state", None):
            self._state = attributes.get("state", None)
            attributes_changed["state"] = self._state
            if (
                self._state is None or self._state == "OFF"
            ) and self.activity.state == "ON":
                self._state = "ON"
        if attributes.get("media_image_url", None):
            self._media_image_url = attributes.get("media_image_url", None)
            attributes_changed["media_image_url"] = True
        if attributes.get("source", None):
            self._current_source = attributes.get("source", None)
            attributes_changed["source"] = self._current_source
        if attributes.get("source_list", None):
            self._source_list = attributes.get("source_list", None)
            attributes_changed["source_list"] = self._source_list
        if attributes.get("media_duration", None):
            self._media_duration = attributes.get("media_duration", 0)
            attributes_changed["media_duration"] = self._media_duration
        if attributes.get("media_artist", None):
            self._media_artist = attributes.get("media_artist", None)
            attributes_changed["media_artist"] = self._media_artist
        if attributes.get("media_album", None):
            self._media_album = attributes.get("media_album", None)
            attributes_changed["media_album"] = self._media_album
        if attributes.get("media_title", None):
            self._media_title = attributes.get("media_title", None)
            attributes_changed["media_title"] = self._media_title
        if attributes.get("media_position", None):
            self._media_position = attributes.get("media_position", 0)
            attributes_changed["media_position"] = self._media_position
        if attributes.get("media_position_updated_at", None):
            self._media_position_updated_at = attributes.get(
                "media_position_updated_at", None
            )
            attributes_changed["media_position_updated_at"] = (
                self._media_position_updated_at
            )
        if attributes.get("muted", None) or attributes.get("muted", None) is False:
            self._muted = attributes.get("muted")
            attributes_changed["muted"] = self._muted
        if attributes.get("media_type", None):
            self._media_type = attributes.get("media_type", None)
            attributes_changed["media_type"] = self._media_type
        if attributes.get("volume", None):
            self._volume = float(attributes.get("volume", None))
        _LOGGER.debug("UC2 attributes changed %s", attributes_changed)
        return attributes_changed

    async def turn_on(self) -> None:
        """Turn on the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.on"}
        if self.activity.power_command:
            body = self.activity.power_command
            entity_id = self.activity.power_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "ON"

    async def turn_off(self) -> None:
        """Turn off the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": self._id, "cmd_id": "media_player.off"}
        if self.activity.power_command:
            body = self.activity.power_command
            entity_id = self.activity.power_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "OFF"

    async def select_source(self, source) -> None:
        """Select source of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        body = {
            "entity_id": self._id,
            "cmd_id": "media_player.select_source",
            "params": {"source": source},
        }
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
        self._current_source = source

    async def volume_up(self) -> None:
        """Raise volume of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.volume_up"}
        if self.activity.volume_up_command:
            body = self.activity.volume_up_command
            entity_id = self.activity.volume_up_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def volume_down(self) -> None:
        """Decrease the volume of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.volume_down"}
        if self.activity.volume_down_command:
            body = self.activity.volume_down_command
            entity_id = self.activity.volume_down_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def mute(self) -> None:
        """Mute the volume of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.mute_toggle"}
        if self.activity.volume_mute_command:
            body = self.activity.volume_mute_command
            entity_id = self.activity.volume_mute_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def volume_set(self, volume: int) -> None:
        """Raise volume of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        int_volume = int(volume)
        entity_id = self.id
        body = {
            "entity_id": entity_id,
            "cmd_id": "media_player.volume",
            "params": {"volume": int_volume},
        }
        if self.activity.volume_mute_command:
            entity_id = self.activity.volume_mute_command.get("entity_id")
            if "media_player." in entity_id:
                body = {
                    "entity_id": entity_id,
                    "cmd_id": "media_player.volume",
                    "params": {"volume": int_volume},
                }
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def play_pause(self) -> None:
        """Play pause the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.play_pause"}
        if self.activity.play_pause_command:
            body = self.activity.play_pause_command
            entity_id = self.activity.play_pause_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def next(self) -> None:
        """Next track/chapter of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.next"}
        if self.activity.next_track_command:
            body = self.activity.next_track_command
            entity_id = self.activity.next_track_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def previous(self) -> None:
        """Previous track/chapter of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.previous"}
        if self.activity.prev_track_command:
            body = self.activity.prev_track_command
            entity_id = self.activity.prev_track_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def stop(self) -> None:
        """Stop the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {"entity_id": entity_id, "cmd_id": "media_player.stop"}
        if self.activity.stop_command:
            body = self.activity.stop_command
            entity_id = self.activity.stop_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def seek(self, position: float) -> None:
        """Skip to given media position of the media player."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        entity_id = self.id
        body = {
            "entity_id": entity_id,
            "cmd_id": "media_player.seek",
            "params": {"media_position": position},
        }
        if self.activity.seek_command:
            body = self.activity.seek_command
            entity_id = self.activity.seek_command.get("entity_id")
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + entity_id + "/command"),
                json=body,
            ) as response,
        ):
            await self._remote.raise_on_error(response)


class ActivityGroup:
    """Class representing a Unfolded Circle Remote Activity Group."""

    def __init__(self, group_id: str, name: str, remote: Remote, state: str) -> None:
        self._id = group_id
        self._remote = remote
        self._state = state
        self._name = name
        self.activities: list[Activity] = []

    @property
    def id(self):
        """id of the Activity."""
        return self._id

    @property
    def name(self):
        """Name of the Activity."""
        return self._name

    @property
    def state(self):
        """State of the Activity group."""
        return self._state

    def get_activity(self, activity_id: str) -> any:
        for activity in self.activities:
            if activity._id == activity_id:
                return activity
        return None

    def is_activity_in_group(self, activity_id: str) -> bool:
        if self.get_activity(activity_id):
            return True
        return False

    async def update(self) -> None:
        """Update activity state information only for active activities."""
        # Find the best media player (if any) entity for each activity group
        for activity in self.activities:
            if activity.is_on():
                await activity.update()


class Activity:
    """Class representing a Unfolded Circle Remote Activity."""

    def __init__(self, activity: str, remote: Remote) -> None:
        """Create activity."""
        self._name = activity["name"]["en"]
        self._id = activity["entity_id"]
        self._remote = remote
        self._state = activity.get("attributes").get("state")
        self._mediaplayer_entities: list[UCMediaPlayerEntity] = []
        self._next_track_command = None
        self._prev_track_command = None
        self._volume_up_command = None
        self._volume_down_command = None
        self._volume_mute_command = None
        self._play_pause_command = None
        self._power_command = None
        self._seek_command = None
        self._stop_command = None

    @property
    def name(self):
        """Name of the Activity."""
        return self._name

    @property
    def id(self):
        """ID of the Activity."""
        return self._id

    @property
    def state(self):
        """State of the Activity."""
        return self._state

    @property
    def remote(self):
        """Remote Object."""
        return self._remote

    @property
    def next_track_command(self):
        """Next Track Command"""
        return self._next_track_command

    @property
    def prev_track_command(self):
        """prev Track Command"""
        return self._prev_track_command

    @property
    def volume_up_command(self):
        """Volume Up Command"""
        return self._volume_up_command

    @property
    def volume_down_command(self):
        """Volume Down Command"""
        return self._volume_down_command

    @property
    def volume_mute_command(self):
        """Volume Mute Command"""
        return self._volume_mute_command

    @property
    def play_pause_command(self):
        """Play Pause Command"""
        return self._play_pause_command

    @property
    def power_command(self):
        """Power Command"""
        return self._power_command

    @property
    def seek_command(self):
        """Seek Command"""
        return self._seek_command

    @property
    def stop_command(self):
        """Stop Command"""
        return self._stop_command

    @property
    def has_media_player_entities(self):
        """Returns true if activity has media players"""
        return len(self._mediaplayer_entities) > 0

    @property
    def mediaplayer_entities(self) -> list[UCMediaPlayerEntity]:
        """Media player entities associated to this activity"""
        return self._mediaplayer_entities

    def add_mediaplayer_entity(self, entity: UCMediaPlayerEntity):
        for existing_entity in self._mediaplayer_entities:
            if existing_entity._id == entity._id:
                return
        self._mediaplayer_entities.append(entity)

    async def turn_on(self) -> None:
        """Turn on an Activity."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        body = {"entity_id": self._id, "cmd_id": "activity.on"}

        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "ON"

    async def turn_off(self) -> None:
        """Turn off an Activity."""
        if self._remote._wake_if_asleep:
            if not await self._remote.wake():
                raise RemoteIsSleeping

        body = {"entity_id": self._id, "cmd_id": "activity.off"}

        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "OFF"

    async def edit(self, options) -> None:
        for attribute, value in options.items():
            match attribute:
                case "prevent_sleep":
                    match value:
                        case True:
                            options = {"options": {"prevent_sleep": True}}

                        case False:
                            options = {"options": {"prevent_sleep": False}}
                case _:
                    pass

        await self.update_activity(options)

    def is_on(self) -> bool:
        """Is Activity Running."""
        return self._state == "ON"

    async def update_activity(self, options) -> None:
        async with (
            self._remote.client() as session,
            session.patch(
                self._remote.url("activities/" + self.id), json=options
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            return await response.json()

    async def update(self) -> None:
        """Update activity state information."""
        activity_info = await self._remote.get_activity(self.id)
        self._state = activity_info["attributes"]["state"]
        try:
            included_entities = activity_info["options"]["included_entities"]
            for entity_info in included_entities:
                if entity_info["entity_type"] != "media_player":
                    continue
                try:
                    entity = self._remote.get_entity(entity_info["entity_id"])
                    entity._entity_commands = entity_info["entity_commands"]
                    entity._name = next(iter(entity_info["name"].values()))
                    await entity.update_data()
                except Exception:
                    pass
        except (KeyError, IndexError):
            pass


def discover_devices(apikey):
    """Zero Conf class."""

    class DeviceListener:
        """Zeroconf Device Listener."""

        def __init__(self) -> None:
            """Discover devices."""
            self.apikey = apikey
            self.devices = []

        def add_service(self, zconf, type_, name):
            """Is Called by zeroconf when something is found."""
            info = zconf.get_service_info(type_, name)
            host = socket.inet_ntoa(info.addresses[0])
            endpoint = f"http://{host}:{info.port}/api/"
            self.devices.append(Remote(endpoint, self.apikey))

        def update_service(self, zconf, type_, name):
            """Nothing."""

        def remove_service(self, zconf, type_, name):
            """Nothing."""

    zconf = zeroconf.Zeroconf(interfaces=zeroconf.InterfaceChoice.Default)
    listener = DeviceListener()
    zeroconf.ServiceBrowser(zconf, ZEROCONF_SERVICE_TYPE, listener)
    try:
        time.sleep(ZEROCONF_TIMEOUT)
    finally:
        zconf.close()
    return RemoteGroup(copy.deepcopy(listener.devices))
