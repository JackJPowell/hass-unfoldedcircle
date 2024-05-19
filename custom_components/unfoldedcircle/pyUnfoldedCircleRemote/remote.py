"""Module to interact with the Unfolded Circle Remote Two."""

import asyncio
import copy
import datetime
import json
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse

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
)

_LOGGER = logging.getLogger(__name__)


class HTTPError(BaseException):
    """Raised when an HTTP operation fails."""

    def __init__(self, status_code, message) -> None:
        """Raise HTTP Error."""
        self.status_code = status_code
        self.message = message
        super().__init__(self.message, self.status_code)


class AuthenticationError(BaseException):
    """Raised when HTTP login fails."""


class SystemCommandNotFound(BaseException):
    """Raised when an invalid system command is supplied."""

    def __init__(self, message) -> None:
        """Raise command no found error."""
        self.message = message
        super().__init__(self.message)


class InvalidIRFormat(BaseException):
    """Raised when invalid or insufficient IR details are passed."""

    def __init__(self, message) -> None:
        """Raise invalid IR format error."""
        self.message = message
        super().__init__(self.message)


class NoEmitterFound(BaseException):
    """Raised when no emitter could be identified from criteria given."""

    def __init__(self, message) -> None:
        """Raise invalid emitter error."""
        self.message = message
        super().__init__(self.message)


class ApiKeyNotFound(BaseException):
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


class RemoteGroup(list):
    """List of Unfolded Circle Remotes."""

    def __init__(self, *args) -> None:
        """Create list of UC Remotes."""
        super().__init__(args[0])


class Remote:
    """Unfolded Circle Remote Class."""

    def __init__(self, api_url, pin=None, apikey=None) -> None:
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
        self._docks = []
        self._ir_custom = []
        self._ir_codesets = []
        self._last_update_type = RemoteUpdateType.NONE
        self._is_simulator = None

    @property
    def name(self):
        """Name of the remote."""
        return self._name or "Unfolded Circle Remote Two"

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
        if self.pin:
            auth = aiohttp.BasicAuth(AUTH_USERNAME, self.pin)
            return aiohttp.ClientSession(
                auth=auth, timeout=aiohttp.ClientTimeout(total=2)
            )

    async def can_connect(self) -> bool:
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

    ### Unfolded Circle API Keys ###
    async def get_api_keys(self) -> str:
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

    @staticmethod
    async def get_version_information(base_url) -> str:
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

    async def get_remote_wifi_info(self) -> str:
        """Get System wifi information from remote. address."""
        if self._is_simulator:
            self._mac_address = SIMULATOR_MAC_ADDRESS
            return
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

            if self._model_name == "Remote Two Simulator":
                self._is_simulator = True
            return information

    async def get_remote_configuration(self) -> str:
        """Get System configuration from remote. User supplied remote name."""
        async with self.client() as session, session.get(self.url("cfg")) as response:
            await self.raise_on_error(response)
            information = await response.json()
            self._name = information.get("device").get("name")
            return information

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
                response2 = await session.get(
                    self.url("activities/" + new_activity._id)
                )
                data = await response2.json()
                try:
                    self.update_activity_entities(
                        new_activity, data["options"]["included_entities"]
                    )
                except (KeyError, IndexError):
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
            await self.raise_on_error(response)
            information = await response.json()
            if information.get("state") == "DOWNLOAD":
                self._update_in_progress = False

            if information.get("state") == "START":
                self._update_in_progress = True
            return information

    async def get_update_status(self) -> str:
        """Update remote status."""
        # WIP: Gets Update Status -- Only supports latest."
        self._download_percent = 0
        async with (
            self.client() as session,
            session.get(self.url("system/update/latest")) as response,
        ):
            await self.raise_on_error(response)
            information = await response.json()
            self._download_percent = information.get("download_percent")
            return information

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
                    self._docks.append(dock_data.copy())
            return self._docks

    async def send_remote_command(
        self, device="", command="", repeat=0, **kwargs
    ) -> bool:
        """Send a remote command to the dock kwargs: code,format,dock,port."""
        body_port = {}
        body_repeat = {}
        if "code" in kwargs and "format" in kwargs:
            # Send an IR command (HEX/PRONTO)
            body = {"code": kwargs.get("code"), "format": kwargs.get("format")}
        if device != "" and command != "":
            # Send a predefined code
            ir_code = next(
                (code for code in self._ir_codesets if code.get("name") == device),
                dict,
            )
            body = {"codeset_id": ir_code.get("device_id"), "cmd_id": command}
        else:
            raise InvalidIRFormat("Supply (code and format) or (device and command)")

        if repeat > 0:
            body_repeat = {"repeat": repeat}

        if "port" in kwargs:
            body_port = {"port_id": kwargs.get("port")}

        if "dock" in kwargs:
            dock_name = kwargs.get("dock")
            emitter = next(
                (dock for dock in self._docks if dock.get("name") == dock_name), None
            )
        else:
            emitter = self._docks[0].get("device_id")

        if emitter is None:
            raise NoEmitterFound("No emitter could be found with the supplied criteria")

        body_merged = {**body, **body_repeat, **body_port}

        async with (
            self.client() as session,
            session.put(
                self.url("ir/emitters/" + emitter + "/send"), json=body_merged
            ) as response,
        ):
            await self.raise_on_error(response)
            response = await response.json()
            return response == 200

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
                _LOGGER.debug("Unfoldded circle remote update light")
                self._ambient_light_intensity = data["msg_data"]["intensity"]
                self._last_update_type = RemoteUpdateType.AMBIENT_LIGHT
                return
            if data["msg"] == "battery_status":
                _LOGGER.debug("Unfoldded circle remote update battery")
                self._battery_status = data["msg_data"]["status"]
                self._battery_level = data["msg_data"]["capacity"]
                self._is_charging = data["msg_data"]["power_supply"]
                self._last_update_type = RemoteUpdateType.BATTERY
                return
            if data["msg"] == "software_update":
                _LOGGER.debug("Unfoldded circle remote software update")
                total_steps = 0
                update_state = "INITIAL"
                current_step = 0
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
                            self._sw_version = self.latest_sw_version
                        case _:
                            self._update_in_progress = False
                            self._update_percent = 0

                self._last_update_type = RemoteUpdateType.SOFTWARE
                return
            if data["msg"] == "configuration_change":
                _LOGGER.debug("Unfoldded circle configuration change")
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
                self._last_update_type = RemoteUpdateType.CONFIGURATION
            if data["msg"] == "power_mode_change":
                _LOGGER.debug("Unfoldded circle Power Mode change")
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
                "Unfoldded circle remote update error while reading data: %s %s",
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
                    "Unfoldded circle remote update link between activity and entities"
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
                _LOGGER.debug("Unfoldded circle remote update activity")
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
            "Unfoldded circle remote update_activity_entities %s %s",
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
            if included_entity.get("name", None) is not None:
                entity._name = next(iter(included_entity["name"].values()))
            if included_entity.get("entity_commands", None) is not None:
                entity._entity_commands = included_entity["entity_commands"]
            activity.add_mediaplayer_entity(entity)

    async def init(self):
        """Retrieves all information about the remote."""
        _LOGGER.debug("Unfoldded circle remote init data")
        group = asyncio.gather(
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
            self.get_activities(),
            self.get_remote_codesets(),
            self.get_docks(),
            self.get_remote_wifi_info(),
        )
        await group

        await self.get_activity_groups()

        for activity_group in self.activity_groups:
            await activity_group.update()
        _LOGGER.debug("Unfoldded circle remote data initialized")

    async def update(self):
        """Updates all information about the remote."""
        _LOGGER.debug("Unfoldded circle remote update data")
        group = asyncio.gather(
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
            self.get_activities_state(),
        )
        await group

        for activity_group in self.activity_groups:
            await activity_group.update()
        _LOGGER.debug("Unfoldded circle remote data updated")

    async def polling_update(self):
        """Updates only polled information from the remote."""
        _LOGGER.debug("Unfoldded circle remote update data")
        group = asyncio.gather(self.get_stats())
        await group


class UCMediaPlayerEntity:
    """Internal class to track the media player entities reported by the remote"""

    def __init__(self, entity_id: str, remote: Remote) -> None:
        self._id = entity_id
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
        self._muted = False
        self._media_image_url = None
        self._entity_commands: list[str] = []
        self._media_position_updated_at = None
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
    def name(self) -> str:
        return self._name

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
    def is_on(self) -> bool:
        if self._state != "OFF":
            return True
        return False

    def update_attributes(self, attributes: any) -> dict[str, any]:
        attributes_changed = {"entity_id": self._id, "name": self.name}
        if attributes.get("state", None):
            self._state = attributes.get("state", None)
            attributes_changed["state"] = self._state
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
            # When media changes, media_duration is sent but not media_position
            # we assume new position to 0
            # if attributes.get("media_position", None) is None:
            #     self._media_position = 0
            #     self._media_position_updated_at = utcnow()
            #     attributes_changed["media_position"] = self._media_position
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
            self._media_position_updated_at = datetime.datetime.utcnow()
            attributes_changed["media_position"] = self._media_position
        if attributes.get("muted", None):
            self._muted = attributes.get("muted", None)
            attributes_changed["muted"] = self._muted
        if attributes.get("media_type", None):
            self._media_type = attributes.get("media_type", None)
            attributes_changed["media_type"] = self._media_type
        _LOGGER.debug("UC2 attributes changed %s", attributes_changed)
        return attributes_changed

    async def turn_on(self) -> None:
        """Turn on the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.on"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "ON"

    async def turn_off(self) -> None:
        """Turn off the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.off"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "OFF"

    async def select_source(self, source) -> None:
        """Select source of the media player."""
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

    async def volume_up(self) -> None:
        """Raise volume of the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.volume_up"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def volume_down(self) -> None:
        """Decrease the volume of the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.volume_down"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def mute(self) -> None:
        """Mute the volume of the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.mute"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def play_pause(self) -> None:
        """Play pause the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.play_pause"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def stop(self) -> None:
        """Stop the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.stop"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def next(self) -> None:
        """Next track/chapter of the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.next"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def previous(self) -> None:
        """Previous track/chapter of the media player."""
        body = {"entity_id": self._id, "cmd_id": "media_player.previous"}
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)

    async def seek(self, position: float) -> None:
        """Next track/chapter of the media player."""
        body = {
            "entity_id": self._id,
            "cmd_id": "media_player.seek",
            "params": {"media_position": position},
        }
        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
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
    def name(self):
        """Name of the Activity."""
        return self._name

    @property
    def id(self):
        """ID of the Activity group."""
        return self._id

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
        body = {"entity_id": self._id, "cmd_id": "activity.off"}

        async with (
            self._remote.client() as session,
            session.put(
                self._remote.url("entities/" + self._id + "/command"), json=body
            ) as response,
        ):
            await self._remote.raise_on_error(response)
            self._state = "OFF"

    def is_on(self) -> bool:
        """Is Activity Running."""
        return self._state == "ON"

    async def update(self) -> None:
        """Update activity state information."""
        activity_info = await self._remote.get_activity(self._id)
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
