"""Config flow for Unfolded Circle Remote integration."""
from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import (
    CONF_PIN,
    CONF_URL,
)

from pyUnfoldedCircleRemote.remote import UCRemote

#from . import ucRemote

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

AUTH_APIKEY_NAME = "pyUnfoldedCircle-dev"
AUTH_USERNAME = "web-configurator"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required("pin"): str, vol.Required("host"): str}
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    remote = UCRemote(data["host"], data["pin"])

    if not await remote.can_connect():
        raise InvalidAuth

    api_key = await UnfoldedCircleRemoteConfigFlow.async_login()
    data["apiKey"] = api_key

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": "Unfolded Circle", "apiKey": api_key}


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        self.api: UCRemote = None
        self.api_keyname: str = None

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry: ConfigEntry) -> UnfoldedCircleRemoteOptionsFlowHandler:
    #     """Get the options flow for this handler."""
    #     return UnfoldedCircleRemoteOptionsFlowHandler(config_entry)

    async def async_setup_api(self, endpoint, unique_id):
        await self.async_set_unique_id(unique_id, raise_on_progress=True)
        self._abort_if_unique_id_configured(updates={CONF_URL: endpoint})

        self.api = UCRemote(endpoint)
        device_info = await self.api.get_remote_information()
        if not device_info:
            raise UCRemote.HTTPError("Unable to retrieve remote information")

        self.context["title_placeholders"] = {"name": self.api.name}

    async def async_login(self, data: dict[str, Any]) -> dict[str, Any]:
        self.api = UCRemote(data["host"], data["pin"])

        if not await self.api.can_connect():
            raise InvalidAuth

        for key in await self.api.get_api_keys():
            if key.get("name") == AUTH_APIKEY_NAME:
                await self.api.revoke_api_key()
        key = await self.api.create_api_key()

        if not key:
            raise UCRemote.HTTPError("Unable to login: failed to create API key")

        data["apiKey"] = key
        return {"title": self.api.name, "apiKey": key}

    # async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
    #     """Handle zeroconf discovery."""
    #     _LOGGER.error("Unfolded Circle Device discovered: %s", endpoint)
    #     host = discovery_info.ip_address
    #     port = discovery_info.port
    #     endpoint = f"http://{host}:{port}/api/"
    #     unique_id = endpoint

    #     try:
    #         await self.async_setup_api(endpoint, unique_id)
    #     except HTTPError:
    #         return self.async_abort(reason="cannot_connect")
    #     else:
    #         _LOGGER.debug("Unfolded Circle Device discovered: %s", endpoint)

    #     return await self.async_step_auth()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self.async_login(user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_auth(self, user_input=None):
        """Provide PIN code in order to authenticate and create an API key."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            pin = user_input[CONF_PIN]
            self.api.pin = pin
            try:
                apikey = await self.async_login()
            except UCRemote.HTTPError as e:
                _LOGGER.warn(
                    "Error while creating API key on %s: %s",
                    self.api.endpoint,
                    e.message,
                )
                errors["base"] = "connection"
            except UCRemote.AuthenticationError as e:
                _LOGGER.warn(
                    "Authentication error on %s: %s",
                    self.api.endpoint,
                    e.message,
                )
                errors["base"] = "auth"
            except TimeoutError as e:
                _LOGGER.warn(
                    "Timed out while creating API key on %s: %s",
                    self.api.endpoint,
                    e.message,
                )
                errors["base"] = "timeout"
            else:
                self.api.apikey = apikey
                self.api_keyname = AUTH_APIKEY_NAME
                return await self.async_step_finish()

        auth_schema = vol.Schema({vol.Required(CONF_PIN): str})
        return self.async_show_form(
            step_id="auth",
            data_schema=auth_schema,
            errors=errors,
        )

class UnfoldedCircleRemoteOptionsFlowHandler(OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, int] | None = None
    ) -> FlowResult:
        """Manage Unfolded Circle options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=STEP_USER_DATA_SCHEMA, )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
