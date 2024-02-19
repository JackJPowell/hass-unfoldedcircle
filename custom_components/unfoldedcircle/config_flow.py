"""Config flow for Unfolded Circle Remote integration."""

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_MAC
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .pyUnfoldedCircleRemote.const import AUTH_APIKEY_NAME
from .pyUnfoldedCircleRemote.remote import AuthenticationError, Remote

from .const import CONF_SERIAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required("pin"): str, vol.Required("host"): str}
)

STEP_ZEROCONF_DATA_SCHEMA = vol.Schema({vol.Required("pin"): str})


async def validate_input(data: dict[str, Any], host: str = "") -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    errors = {}
    if host != "":
        remote = Remote(host, data["pin"])
    else:
        remote = Remote(data["host"], data["pin"])

    try:
        await remote.can_connect()
    except AuthenticationError as err:
        _LOGGER.exception(err)
        raise InvalidAuth from err
    except Exception as ex:  # pylint: disable=broad-except
        _LOGGER.exception(ex)
        errors["base"] = "unknown"
        raise CannotConnect from ex

    for key in await remote.get_api_keys():
        if key.get("name") == AUTH_APIKEY_NAME:
            await remote.revoke_api_key()

    key = await remote.create_api_key()
    await remote.get_remote_information()

    if not key:
        raise InvalidAuth("Unable to login: failed to create API key")

    # api_key = await UnfoldedCircleRemoteConfigFlow.async_login()
    await remote.get_remote_information()
    await remote.get_remote_configuration()
    await remote.get_remote_wifi_info()

    mac_address = None
    if remote._address:
        mac_address = remote._address.replace(":", "").lower()

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        "title": remote.name,
        "apiKey": key,
        "host": remote.endpoint,
        "pin": data["pin"],
        "address": remote._address,
        "ip_address": remote._ip_address,
        CONF_SERIAL: remote.serial_number,
        CONF_MAC: mac_address
    }


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

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry: ConfigEntry) -> UnfoldedCircleRemoteOptionsFlowHandler:
    #     """Get the options flow for this handler."""
    #     return UnfoldedCircleRemoteOptionsFlowHandler(config_entry)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Handle zeroconf discovery."""
        host = discovery_info.ip_address.compressed
        port = discovery_info.port
        hostname = discovery_info.hostname # RemoteTwo-AABBCCDDEEFF-2.local. where AABBCCDDEEFF = mac address
        name = discovery_info.name  # RemoteTwo-AABBCCDDEEFF-2.local. where AABBCCDDEEFF = mac address
        endpoint = f"http://{host}:{port}/api/"

        mac_address = None
        try:
            mac_address = re.match("^[^-]+-([^-]+)-", hostname).group(1).lower()
        except Exception:
            try:
                mac_address = re.match("^[^-]+-([^-]+)-", name).group(1).lower()
            except Exception:
                pass

        self.discovery_info.update(
            {CONF_HOST: host, CONF_PORT: port, CONF_NAME: "Remote Two ("+host+")", CONF_MAC: mac_address}
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

        # Other approach : abandonned
        # existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        # if existing_entries:
        #     for existing_entry in existing_entries:
        #         try:
        #             ip_address = existing_entry.data.get("ip_address")
        #             for ip_address2 in discovery_info.ip_addresses:
        #                 if ip_address == ip_address2.compressed:
        #                     _LOGGER.debug("Unfolded circle remote discovered already configured %s", discovery_info)
        #                     raise data_entry_flow.AbortFlow("already_configured")
        #                     #self._abort_if_unique_id_configured(existing_entry[CONF_SERIAL])
        #         except (KeyError, IndexError):
        #             pass

        _LOGGER.debug("Unfolded circle remote found %s %s :", host, discovery_info)

        # Use mac address as unique id as this is the only common information between zeroconf and user conf
        if mac_address:
            await self._async_set_unique_id_and_abort_if_already_configured(mac_address)

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
            self.discovery_info.update(
                {CONF_MAC: info[CONF_MAC]}
            )
            # Check unique ID here based on serial number
            await self._async_set_unique_id_and_abort_if_already_configured(info[CONF_MAC])

        except CannotConnect as ex:
            _LOGGER.error(ex)
        except InvalidAuth as ex:
            _LOGGER.error(ex)
        else:
            return self.async_create_entry(
                title=info.get("title"),
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
            self.discovery_info.update(
                {CONF_MAC: info[CONF_MAC]}
            )
            # Check unique ID here based on serial number
            await self._async_set_unique_id_and_abort_if_already_configured(info[CONF_MAC])
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
            existing_entry = await self.async_set_unique_id(self.reauth_entry.unique_id)
            _LOGGER.debug("RC2 existing_entry %s", existing_entry)
            info = await validate_input(user_input, self.reauth_entry.data[CONF_HOST])
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
            existing_entry = await self.async_set_unique_id(self.reauth_entry.unique_id)
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
