"""Config flow for Unfolded Circle Remote integration."""

import logging
import re
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from pyUnfoldedCircleRemote.const import (
    AUTH_APIKEY_NAME,
    SIMULATOR_MAC_ADDRESS,
)
from .helpers import validate_dock_password
from pyUnfoldedCircleRemote.remote import AuthenticationError, Remote

from .const import (
    CONF_ACTIVITIES_AS_SWITCHES,
    CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
    CONF_ACTIVITY_MEDIA_ENTITIES,
    CONF_GLOBAL_MEDIA_ENTITY,
    CONF_SERIAL,
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
)


_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("pin"): str,
    }
)

STEP_ZEROCONF_DATA_SCHEMA = vol.Schema({vol.Required("pin"): str})


async def generate_token(hass: HomeAssistant, name):
    """Generate a token for Unfolded Circle to use with HA API"""
    user = await hass.auth.async_get_owner()
    try:
        token = await hass.auth.async_create_refresh_token(
            user=user,
            client_name=name,
            client_icon="",
            token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
            access_token_expiration=timedelta(days=3652),
        )
    except ValueError:
        _LOGGER.warning("There is already a long lived token with %s name", name)
        return None

    return hass.auth.async_create_access_token(token)


async def remove_token(hass: HomeAssistant, token):
    """Remove api token from remote"""
    _LOGGER.debug("Removing refresh token")
    refresh_token = await hass.auth.async_get_refresh_token_by_token(token)
    await hass.auth.async_remove_refresh_token(refresh_token)


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any], host: str = ""
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    if host != "":
        remote = Remote(host, data["pin"])
    else:
        remote = Remote(data["host"], data["pin"])

    try:
        await remote.validate_connection()
    except AuthenticationError as err:
        raise InvalidAuth from err
    except ConnectionError as ex:
        raise CannotConnect from ex

    for key in await remote.get_api_keys():
        if key.get("name") == AUTH_APIKEY_NAME:
            await remote.revoke_api_key()

    url = get_url(hass)
    key = await remote.create_api_key()
    await remote.get_remote_information()
    await remote.get_remote_configuration()
    await remote.get_remote_wifi_info()
    await remote.get_docks()
    # token = await generate_token(hass, remote.name)
    # token_id = await remote.set_token_for_external_system(
    #     "hass",
    #     "hass_id",
    #     token,
    #     "Home Assistant",
    #     "Home Assistant Long Lived Access Token",
    #     url,
    #     "data",
    # )

    if not key:
        raise InvalidAuth("Unable to login: failed to create API key")

    mac_address = None
    if remote.mac_address:
        mac_address = remote.mac_address.replace(":", "").lower()

    docks = []
    for dock in remote._docks:
        docks.append({"id": dock.id, "name": dock.name, "password": ""})

    # Return info that you want to store in the config entry.
    return {
        "title": remote.name,
        "apiKey": key,
        "host": remote.endpoint,
        "pin": data["pin"],
        "mac_address": remote.mac_address,
        "ip_address": remote.ip_address,
        # "token": token,
        # "token_id": token_id,
        CONF_SERIAL: remote.serial_number,
        CONF_MAC: mac_address,
        "docks": docks,
    }, remote


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    reauth_entry: ConfigEntry | None = None

    def __init__(self) -> None:
        """Unfolded Circle Config Flow."""
        self.api: Remote = None
        self.api_keyname: str = None
        self.discovery_info: dict[str, Any] = {}
        self.dock_count: int = 0
        self.info: dict[str, any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ):
        """Get the options flow for this handler."""
        return UnfoldedCircleRemoteOptionsFlowHandler(config_entry)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Handle zeroconf discovery."""
        host = discovery_info.ip_address.compressed
        port = discovery_info.port
        hostname = discovery_info.hostname
        name = discovery_info.name
        model = discovery_info.properties.get("model")
        endpoint = f"http://{host}:{port}/api/"

        mac_address = None
        try:
            mac_address = re.match(r"RemoteTwo-(.*?)\.", hostname).group(1).lower()
        except Exception:
            try:
                mac_address = re.match(r"RemoteTwo-(.*?)\.", name).group(1).lower()
            except Exception:
                if model != "UCR2-simulator":
                    return self.async_abort(reason="no_mac")
                _LOGGER.debug("Zeroconf from the Simulator %s", discovery_info)
                mac_address = SIMULATOR_MAC_ADDRESS.replace(":", "").lower()

        self.discovery_info.update(
            {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_NAME: f"Remote Two ({host})",
                CONF_MAC: mac_address,
            }
        )

        _LOGGER.debug(
            "Unfolded circle remote found %s %s %s :",
            mac_address,
            host,
            discovery_info,
        )

        # Use mac address as unique id as this is the only common
        # information between zeroconf and user conf
        if mac_address:
            await self._async_set_unique_id_and_abort_if_already_configured(mac_address)

        # Retrieve device friendly name set by the user

        configuration_url = ""
        device_name = ""
        match model:
            case "UCR2":
                device_name = "Remote Two"
                configuration_url = (
                    f"http://{discovery_info.host}:{discovery_info.port}/configurator/"
                )
                try:
                    response = await Remote.get_version_information(endpoint)
                    device_name = response.get("device_name", None)
                    if not device_name:
                        device_name = "Remote Two"
                except Exception:
                    pass
            case "UCR2-simulator":
                device_name = "Remote Two Simulator"
                configuration_url = (
                    f"http://{discovery_info.host}:{discovery_info.port}/configurator/"
                )

        self.context.update(
            {
                "title_placeholders": {"name": device_name},
                "configuration_url": configuration_url,
                "product": "Product",
            }
        )

        _LOGGER.debug(
            "Unfolded Circle Zeroconf Creating: %s %s",
            mac_address,
            discovery_info,
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        errors: dict[str, str] = {}
        if user_input is None or user_input == {}:
            return self.async_show_form(
                step_id="zeroconf_confirm",
                data_schema=STEP_ZEROCONF_DATA_SCHEMA,
                errors={},
            )
        try:
            host = f"{self.discovery_info[CONF_HOST]}:{self.discovery_info[CONF_PORT]}"
            info, self.api = await validate_input(self.hass, user_input, host)
            self.discovery_info.update({CONF_MAC: info[CONF_MAC]})
            # Check unique ID here based on serial number
            await self._async_set_unique_id_and_abort_if_already_configured(
                info[CONF_MAC]
            )

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        else:
            if info["docks"]:
                return await self.async_step_dock(info=info, first_call=True)

            return self.async_create_entry(title=info["title"], data=info)

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=STEP_ZEROCONF_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is None or user_input == {}:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors=errors,
                last_step=False,
            )

        try:
            info, self.api = await validate_input(self.hass, user_input, "")
            self.discovery_info.update({CONF_MAC: info[CONF_MAC]})
            await self._async_set_unique_id_and_abort_if_already_configured(
                info[CONF_MAC]
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            if info["docks"]:
                return await self.async_step_dock(info=info, first_call=True)

            return self.async_create_entry(title=info["title"], data=info)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            last_step=False,
        )

    async def async_step_dock(
        self,
        user_input: dict[str, Any] | None = None,
        info: dict[str, any] = None,
        first_call: bool = False,
    ) -> FlowResult:
        """Called if there are docks associated with the remote"""
        schema = {}
        errors: dict[str, str] = {}
        if info:
            self.info = info

        dock_total = len(self.info["docks"])
        if dock_total >= self.dock_count:
            dock_info = self.info["docks"][self.dock_count]

            schema[vol.Optional("password")] = str
            placeholder = {
                "name": dock_info.get("name"),
                "count": f"({self.dock_count + 1}/{dock_total})",
            }

            if user_input is None or user_input == {}:
                if first_call is False:
                    self.dock_count += 1
                    if dock_total == self.dock_count:
                        return self.async_create_entry(
                            title=self.info["title"], data=self.info
                        )
                return self.async_show_form(
                    step_id="dock",
                    data_schema=vol.Schema(schema),
                    description_placeholders=placeholder,
                    errors=errors,
                    last_step=True,
                )

        try:
            self.info["docks"][self.dock_count]["password"] = user_input["password"]
            is_valid = await validate_dock_password(self.api, dock_info)
            if is_valid:
                self.dock_count += 1
            else:
                self.info["docks"][self.dock_count]["password"] = ""
                raise InvalidDockPassword

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidDockPassword:
            errors["base"] = "invalid_dock_password"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        if dock_total == self.dock_count:
            return self.async_create_entry(title=self.info["title"], data=self.info)

        return self.async_show_form(
            step_id="dock",
            errors=errors,
            description_placeholders=placeholder,
            data_schema=vol.Schema(schema),
            last_step=True,
        )

    async def _async_set_unique_id_and_abort_if_already_configured(
        self, unique_id: str
    ) -> None:
        """Set the unique ID and abort if already configured."""
        await self.async_set_unique_id(unique_id, raise_on_progress=False)
        self._abort_if_unique_id_configured(
            updates={CONF_MAC: self.discovery_info[CONF_MAC]},
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        user_input["pin"] = None
        user_input["apiKey"] = None
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        errors = {}
        if user_input is None:
            user_input = {}

        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        _LOGGER.debug("RC2 async_step_reauth_confirm %s", self.reauth_entry)

        if user_input.get("pin") is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=STEP_ZEROCONF_DATA_SCHEMA
            )

        try:
            existing_entry = await self.async_set_unique_id(
                self.reauth_entry.unique_id, raise_on_progress=False
            )
            _LOGGER.debug("RC2 existing_entry %s", existing_entry)
            info, self.api = await validate_input(
                self.hass, user_input, self.reauth_entry.data[CONF_HOST]
            )
        except CannotConnect:
            _LOGGER.exception("Cannot Connect")
            errors["base"] = "Cannot Connect"
        except InvalidAuth:
            _LOGGER.exception("Invalid PIN")
            errors["base"] = "Invalid PIN"
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.exception(ex)
            errors["base"] = "unknown"
        else:
            existing_entry = await self.async_set_unique_id(
                self.reauth_entry.unique_id, raise_on_progress=False
            )
            if existing_entry:
                self.hass.config_entries.async_update_entry(existing_entry, data=info)
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            return self.async_create_entry(
                title=info["title"],
                data=info,
            )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_ZEROCONF_DATA_SCHEMA,
            errors=errors,
        )


class UnfoldedCircleRemoteOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_activities()

    async def async_step_activities(self, user_input=None):
        """Handle options step two flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_media_player()

        return self.async_show_form(
            step_id="activities",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ACTIVITIES_AS_SWITCHES,
                        default=self.config_entry.options.get(
                            CONF_ACTIVITIES_AS_SWITCHES, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SUPPRESS_ACTIVITIY_GROUPS,
                        default=self.config_entry.options.get(
                            CONF_SUPPRESS_ACTIVITIY_GROUPS, False
                        ),
                    ): bool,
                }
            ),
            last_step=False,
        )

    async def async_step_media_player(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="media_player",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_GLOBAL_MEDIA_ENTITY,
                        default=self.config_entry.options.get(
                            CONF_GLOBAL_MEDIA_ENTITY, True
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
                        default=self.config_entry.options.get(
                            CONF_ACTIVITY_GROUP_MEDIA_ENTITIES, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ACTIVITY_MEDIA_ENTITIES,
                        default=self.config_entry.options.get(
                            CONF_ACTIVITY_MEDIA_ENTITIES, False
                        ),
                    ): bool,
                }
            ),
            last_step=True,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class InvalidDockPassword(HomeAssistantError):
    """Error to indicate an invalid dock password was supplied"""
