"""Config flow for Unfolded Circle Remote integration."""
from __future__ import annotations

import logging
from typing import Any

from pyUnfoldedCircleRemote.remote import UCRemote
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PIN, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

# from . import ucRemote
from .const import CONF_SERIAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

AUTH_APIKEY_NAME = "pyUnfoldedCircle"
AUTH_USERNAME = "web-configurator"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required("pin"): str, vol.Required("host"): str}
)

STEP_ZEROCONF_DATA_SCHEMA = vol.Schema({vol.Required("pin"): str})


async def validate_input(data: dict[str, Any], host: str = "") -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    if host != "":
        remote = UCRemote(host, data["pin"])
    else:
        remote = UCRemote(data["host"], data["pin"])

    if not await remote.can_connect():
        raise InvalidAuth

    for key in await remote.get_api_keys():
        if key.get("name") == AUTH_APIKEY_NAME:
            await remote.revoke_api_key()

    key = await remote.create_api_key()
    await remote.get_remote_information()

    if not key:
        raise InvalidAuth("Unable to login: failed to create API key")

    # api_key = await UnfoldedCircleRemoteConfigFlow.async_login()
    await remote.get_remote_information()

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        "title": "Remote Two",
        "apiKey": key,
        "host": remote.endpoint,
        "pin": data["pin"],
        CONF_SERIAL: remote.serial_number,
    }

class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        self.api: UCRemote = None
        self.api_keyname: str = None
        self.discovery_info: dict[str, Any] = {}

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry: ConfigEntry) -> UnfoldedCircleRemoteOptionsFlowHandler:
    #     """Get the options flow for this handler."""
    #     return UnfoldedCircleRemoteOptionsFlowHandler(config_entry)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Handle zeroconf discovery."""
        host = discovery_info.ip_address.compressed
        port = discovery_info.port
        hostname = discovery_info.hostname
        endpoint = f"http://{host}:{port}/api/"

        self.discovery_info.update(
            {CONF_HOST: host, CONF_PORT: port, CONF_NAME: "Remote Two"}
        )

        self.context.update(
            {
                "title_placeholders": {"name": "Remote Two"},
                "configuration_url": (
                    f"http://{discovery_info.host}:{discovery_info.port}/configurator/"
                ),
                "product": "Product",
            }
        )

        if hostname:
            await self._async_set_unique_id_and_abort_if_already_configured(hostname)

        _LOGGER.debug("Unfolded Circle Device discovered: %s", endpoint)

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        errors: dict[str, str] | None = None
        if user_input is None or user_input == {}:
            return self.async_show_form(
                step_id="zeroconf_confirm",
                data_schema=STEP_ZEROCONF_DATA_SCHEMA,
                errors={},
            )
        try:
            info = await validate_input(user_input, self.discovery_info[CONF_HOST])
        except CannotConnect as ex:
            _LOGGER.error(ex)
            errors = {"base": ex.error_code}
        except InvalidAuth as ex:
            _LOGGER.error(ex)
            errors = {"base": ex.error_code}
        else:
            return self.async_create_entry(
                title="Remote two",
                data=info,
            )

        # self.context["title_placeholders"] = {
        #     "name": f"{self.discovery.product_name} ({self.discovery.serial})"
        # }

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
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        try:
            info = await validate_input(user_input, "")
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=info)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def _async_set_unique_id_and_abort_if_already_configured(
        self, unique_id: str
    ) -> None:
        """Set the unique ID and abort if already configured."""
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: self.discovery_info[CONF_HOST]},
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

        return self.async_show_form(
            step_id="init",
            data_schema=STEP_USER_DATA_SCHEMA,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
