"""Config flow for Unfolded Circle Remote integration."""

# This module groups Home Assistant config and options flow handlers.
# pylint: disable=too-many-lines

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiohttp import ClientConnectionError
from unfurled.helpers.exceptions import (
    ApiKeyError,
    AuthenticationError,
    ConnectionError as RemoteConnectionError,
    TokenRegistrationError,
)
from unfurled.remote import Remote
import voluptuous as vol
from voluptuous import Optional, Required

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_ACTIVITIES_AS_SWITCHES,
    CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
    CONF_ACTIVITY_MEDIA_ENTITIES,
    CONF_DIRECT_DOCK_COMMUNICATION,
    CONF_GLOBAL_MEDIA_ENTITY,
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
    HA_SUPPORTED_DOMAINS,
    REMOTE_ON_BEHAVIOR,
)
from .helpers import (
    InvalidWebsocketAddress,
    UnableToDetermineUser,
    connect_integration,
    get_ha_websocket_url,
    get_registered_websocket_url,
    validate_and_register_system_and_driver,
    validate_websocket_address,
)
from .websocket import UCWebsocketClient

_LOGGER = logging.getLogger(__name__)
CONF_DOCK_ID = "dock_id"
CONF_SERIAL = "serial"
CONF_HA_WEBSOCKET_URL = "ha_ws_url"


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    reauth_entry: ConfigEntry | None = None

    VERSION = 6

    def __init__(self) -> None:
        """Unfolded Circle Config Flow."""
        self.discovery_info: dict[str, Any] = {}
        self._remote: Remote | None = None
        self._reconfigure_entry: ConfigEntry | None = None
        self.info: dict[str, any] = {}
        self.options: dict[str, any] = {}

    async def validate_input(
        self, data: dict[str, Any], host: str = ""
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.
        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        endpoint = host if host else data["host"]
        self._remote = Remote(endpoint, pin=data["pin"])

        websocket_url = data.get(CONF_HA_WEBSOCKET_URL, get_ha_websocket_url(self.hass))
        validate_websocket_address(websocket_url)

        try:
            await self._remote.validate_connection()
            _LOGGER.debug("Connection successful to %s", self._remote.endpoint)
        except AuthenticationError as err:
            raise InvalidAuth from err
        except RemoteConnectionError as ex:
            raise CannotConnect from ex
        except ConnectionError as ex:
            raise CannotConnect from ex

        key = None
        try:
            key = await self._remote.auth.rotate_key()
        except ApiKeyError as ex:
            _LOGGER.error("Could not rotate API key: %s", ex)

        if not key:
            raise InvalidAuth("Unable to login: failed to create API key")
        _LOGGER.debug("Remote registered successfully, retrieving information...")

        # Update the api_key on the remote now that we have it
        self._remote.set_api_key(key)

        try:
            await self._remote.init()
        except Exception as ex:
            _LOGGER.error("Error during extraction of remote information: %s", ex)

        # Call helper to register a new external system with the remote if needed
        if self._remote.system.flags.external_entity_configuration_available:
            try:
                await validate_and_register_system_and_driver(
                    self._remote,
                    self.hass,
                    websocket_url,
                )
            except TokenRegistrationError as ex:
                _LOGGER.error("Error during external system registration %s", ex)
            except InvalidWebsocketAddress as ex:
                _LOGGER.error("Invalid websocket address supplied %s", ex)
            except Exception as ex:
                _LOGGER.error(
                    "Error during driver registration, continue config flow: %s", ex
                )

        mac_address = None
        if self._remote.device.mac_address:
            mac_address = self._remote.device.mac_address.replace(":", "").lower()

        return {
            "title": self._remote.device.name,
            "apiKey": key,
            "host": self._remote.endpoint,
            "pin": data["pin"],
            "mac_address": self._remote.device.mac_address,
            "ip_address": self._remote.device.ip_address,
            CONF_SERIAL: self._remote.device.serial_number,
            CONF_MAC: mac_address,
        }

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
        port = discovery_info.port or 80  # Default to 80 if port is None
        model = discovery_info.properties.get("model")

        info = await Remote.resolve_discovery(
            discovery_info.ip_address.compressed,
            port,
            discovery_info.properties.get("model", ""),
        )
        device_name = info["name"]
        configuration_url = info["configuration_url"]
        mac_address = info["mac_address"]
        remote_name = Remote.name_from_model_id(model)
        self.discovery_info.update(
            {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_NAME: f"{remote_name} ({host})",
                CONF_MAC: mac_address,
            }
        )

        _LOGGER.debug(
            "Unfolded Circle remote found via mDNS: %s at %s:%s",
            mac_address,
            host,
            port,
        )
        if not mac_address:
            return self.async_abort(reason="no_mac")

        # Set unique ID and update host/port if already configured (for IP address changes)
        await self._async_set_unique_id_and_abort_if_already_configured(
            mac_address, host=host, port=port
        )

        self.context.update(
            {
                "title_placeholders": {"name": device_name},
                "configuration_url": configuration_url,
                "product": "Product",
            }
        )

        _LOGGER.debug(
            "Unfolded Circle Zeroconf Creating: %s %s", mac_address, discovery_info
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        errors: dict[str, str] = {}
        zero_config_data_schema: dict[Required | Optional, type] = vol.Schema(
            {
                vol.Required("pin"): str,
                vol.Optional(
                    CONF_HA_WEBSOCKET_URL, default=get_ha_websocket_url(self.hass)
                ): str,
                vol.Optional(CONF_ACTIVITIES_AS_SWITCHES, default=False): bool,
                vol.Optional(CONF_DIRECT_DOCK_COMMUNICATION, default=False): bool,
            }
        )
        if user_input is None or user_input == {}:
            name = Remote.name_from_model_id(self.discovery_info.get("model"))

            return self.async_show_form(
                step_id="zeroconf_confirm",
                data_schema=zero_config_data_schema,
                description_placeholders={"name": name},
                errors={},
            )
        try:
            host = f"{self.discovery_info[CONF_HOST]}:{self.discovery_info[CONF_PORT]}"
            self.info = await self.validate_input(user_input, host)
            self.discovery_info.update({CONF_MAC: self.info[CONF_MAC]})
            # Store the activities_as_switches option
            if user_input.get(CONF_ACTIVITIES_AS_SWITCHES) is not None:
                self.options[CONF_ACTIVITIES_AS_SWITCHES] = user_input[
                    CONF_ACTIVITIES_AS_SWITCHES
                ]
            self.options[CONF_DIRECT_DOCK_COMMUNICATION] = user_input.get(
                CONF_DIRECT_DOCK_COMMUNICATION, False
            )
            await self._async_set_unique_id_and_abort_if_already_configured(
                self.info[CONF_MAC]
            )

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotCreateHAToken:
            errors["base"] = "cannot_create_ha_token"
        except InvalidWebsocketAddress:
            errors["base"] = "invalid_websocket_address"
        else:
            if self._remote.system.flags.external_entity_configuration_available:
                return await self.async_step_select_entities(None)
            return await self.async_step_finish(None)

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=zero_config_data_schema,
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {"dock": DockSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is None or user_input == {}:
            schema: dict[Required | Optional, type] = vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("pin"): str,
                    vol.Optional(
                        CONF_HA_WEBSOCKET_URL, default=get_ha_websocket_url(self.hass)
                    ): str,
                    vol.Optional(CONF_ACTIVITIES_AS_SWITCHES, default=False): bool,
                    vol.Optional(CONF_DIRECT_DOCK_COMMUNICATION, default=False): bool,
                }
            )
            return self.async_show_form(
                step_id="user", data_schema=schema, errors=errors
            )

        try:
            _LOGGER.debug("Connect with manual input: %s", user_input)
            self.info = await self.validate_input(user_input, "")
            self.discovery_info.update({CONF_MAC: self.info[CONF_MAC]})
            # Store the activities_as_switches option
            if user_input.get(CONF_ACTIVITIES_AS_SWITCHES) is not None:
                self.options[CONF_ACTIVITIES_AS_SWITCHES] = user_input[
                    CONF_ACTIVITIES_AS_SWITCHES
                ]
            self.options[CONF_DIRECT_DOCK_COMMUNICATION] = user_input.get(
                CONF_DIRECT_DOCK_COMMUNICATION, False
            )
            await self._async_set_unique_id_and_abort_if_already_configured(
                self.info[CONF_MAC]
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotCreateHAToken:
            errors["base"] = "cannot_create_ha_token"
        except InvalidWebsocketAddress:
            errors["base"] = "invalid_websocket_address"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            if self._remote.system.flags.external_entity_configuration_available:
                return await self.async_step_select_entities(None)
            return await self.async_step_finish(None)

        schema: dict[Required | Optional, type] = vol.Schema(
            {
                vol.Required("host", default=user_input.get("host")): str,
                vol.Required("pin"): str,
                vol.Optional(
                    CONF_HA_WEBSOCKET_URL, default=user_input.get(CONF_HA_WEBSOCKET_URL)
                ): str,
                vol.Optional(
                    CONF_ACTIVITIES_AS_SWITCHES,
                    default=user_input.get(CONF_ACTIVITIES_AS_SWITCHES, False),
                ): bool,
                vol.Optional(
                    CONF_DIRECT_DOCK_COMMUNICATION,
                    default=user_input.get(CONF_DIRECT_DOCK_COMMUNICATION, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_set_unique_id_and_abort_if_already_configured(
        self, unique_id: str, host: str | None = None, port: int | None = None
    ) -> None:
        """Set the unique ID and abort if already configured.

        If host and port are provided (from mDNS discovery), update the config entry's
        host field and reload the integration when the IP address changes.
        """
        # Legacy dash check for compatibility (though remote MACs don't have dashes)
        index = unique_id.find("-")
        if index > 0:
            unique_id = unique_id[0:index]

        await self.async_set_unique_id(unique_id)

        # If host/port provided (from mDNS), update them and reload on change
        if host is not None and port is not None:
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: f"{host}:{port}", CONF_MAC: unique_id},
                reload_on_update=True,
            )
        else:
            # Standard behavior for manual config
            self._abort_if_unique_id_configured(
                updates={CONF_MAC: unique_id},
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
        zero_config_data_schema: dict[Required | Optional, type] = vol.Schema(
            {
                vol.Required("pin"): str,
            }
        )
        if user_input is None:
            user_input = {}

        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        _LOGGER.debug("UC async_step_reauth_confirm %s", self.reauth_entry)

        if user_input.get("pin") is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=zero_config_data_schema
            )

        try:
            existing_entry = await self.async_set_unique_id(
                self.reauth_entry.unique_id, raise_on_progress=False
            )
            _LOGGER.debug("UC existing_entry %s", existing_entry)
            info = await self.validate_input(
                user_input, self.reauth_entry.data[CONF_HOST]
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotCreateHAToken:
            errors["base"] = "cannot_create_ha_token"
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

            return self.async_create_entry(title=info["title"], data=info)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=zero_config_data_schema,
            errors=errors,
        )

    async def async_step_select_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selected entities to subscribe to."""
        return await async_step_select_entities(
            self,
            self._remote,
            self.async_step_finish,
            user_input,
        )

    async def async_step_fix_ws(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fix WebSocket URL Step"""
        return await async_step_fix_ws(
            self,
            self.hass,
            self._remote,
            self.async_step_select_entities,
            user_input,
        )

    async def async_step_finish(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Complete config flow"""
        _LOGGER.debug("Create registry entry")
        try:
            result = self.async_create_entry(
                title=self.info["title"], data=self.info, options=self.options
            )
            _LOGGER.debug("Registry entry creation result : %s", result)
            return result
        except Exception as ex:
            _LOGGER.error("Error while creating registry entry %s", ex)
            raise ex

    async def async_step_reconfigure(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the integration."""
        self._reconfigure_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._remote = Remote(
            api_url=self._reconfigure_entry.data["host"],
            api_key=self._reconfigure_entry.data["apiKey"],
        )
        try:
            await self._remote.validate_connection()
            await self._remote.init()
        except Exception:
            pass  # Continue anyway, we're reconfiguring

        if self._remote.system.flags.external_entity_configuration_available:
            return self.async_show_menu(
                step_id="reconfigure",
                menu_options=["reconfigure_host", "reconfigure_websocket"],
            )
        return await self.async_step_reconfigure_host()

    async def async_step_reconfigure_host(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the remote host."""
        return await async_step_remote_host(
            self,
            self.hass,
            self._remote,
            self._reconfigure_entry,
            self.async_step_reconfigure_finish,
            user_input,
            step_id="reconfigure_host",
        )

    async def async_step_reconfigure_websocket(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the websocket URL."""
        return await async_step_websocket(
            self,
            self.hass,
            self._remote,
            self.async_step_reconfigure_finish,
            user_input,
            step_id="reconfigure_websocket",
        )

    async def async_step_reconfigure_finish(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish reconfiguration."""
        return self.async_update_reload_and_abort(
            self._reconfigure_entry,
            data=self._reconfigure_entry.data,
        )


class DockSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and modifying a dock."""

    def __init__(self) -> None:
        """Unfolded Circle SubEntry Config Flow."""
        self.config_entry: ConfigEntry | None = None
        self.runtime_data = None
        self.remote = None
        self.current_dock = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to add a new dock."""
        self.config_entry = self._get_entry()
        self.runtime_data = self.config_entry.runtime_data
        self.remote = self.runtime_data.remote

        configured_ids = {
            data.unique_id for _, data in self.config_entry.subentries.items()
        }
        available_docks = [
            dock
            for dock in self.remote.docks
            if f"{self.config_entry.unique_id}_{dock.device.id}" not in configured_ids
        ]

        docks_to_display = {}
        if not available_docks:
            return self.async_abort(reason="no_docks_available")

        if len(available_docks) == 1:
            return await self.async_step_dock(
                user_input=None, dock_info=available_docks[0], first_call=True
            )

        if user_input is not None:
            dock = next(
                (
                    dock
                    for dock in available_docks
                    if dock.device.id == user_input.get(CONF_DOCK_ID)
                ),
                None,
            )
            return await self.async_step_dock(
                user_input=None, dock_info=dock, first_call=True
            )

        if user_input is None or user_input == {}:
            for dock in available_docks:
                docks_to_display[dock.device.id] = dock.device.name

            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_DOCK_ID): vol.In(docks_to_display)}
                ),
                errors={},
            )
        return await self.async_step_user(user_input)

    async def async_step_dock(
        self,
        user_input: dict[str, Any] | None = None,
        dock_info: Any | None = None,
        first_call: bool = False,
    ) -> FlowResult:
        """Called if there are docks associated with the remote"""
        schema = {}
        errors: dict[str, str] = {}
        placeholder: dict[str, any] | None = None
        dock_data: dict[str, Any] = {}

        if dock_info:
            self.current_dock = dock_info

        schema[vol.Optional("password")] = str
        placeholder = {"name": self.current_dock.device.name}

        if user_input is None or user_input == {}:
            if first_call is True:
                dock_data["id"] = self.current_dock.device.id
                dock_data["password"] = "0000"
                dock_data["name"] = self.current_dock.device.name
                if not self.config_entry.options.get(
                    CONF_DIRECT_DOCK_COMMUNICATION, False
                ):
                    return self.async_create_entry(
                        title=dock_data["name"],
                        data=dock_data,
                        unique_id=f"{self.config_entry.unique_id}_{dock_data['id']}",
                    )

                if not await self.current_dock.validate_password(dock_data["password"]):
                    return self.async_show_form(
                        step_id="dock",
                        data_schema=vol.Schema(schema),
                        description_placeholders=placeholder,
                        errors=errors,
                        last_step=True,
                    )
                return self.async_create_entry(
                    title=dock_data["name"],
                    data=dock_data,
                    unique_id=f"{self.config_entry.unique_id}_{dock_data['id']}",
                )

            return self.async_show_form(
                step_id="dock",
                data_schema=vol.Schema(schema),
                description_placeholders=placeholder,
                errors=errors,
                last_step=True,
            )

        password = user_input.get("password", "")
        if not await self.current_dock.validate_password(password):
            errors["base"] = "invalid_dock_password"

        if errors:
            return self.async_show_form(
                step_id="dock",
                data_schema=vol.Schema(schema),
                description_placeholders=placeholder,
                errors=errors,
                last_step=True,
            )
        data = {
            "id": self.current_dock.device.id,
            "name": self.current_dock.device.name,
            "password": password,
        }
        return self.async_create_entry(
            title=self.current_dock.device.name,
            data=data,
            unique_id=f"{self.config_entry.unique_id}_{self.current_dock.device.id}",
        )


class UnfoldedCircleRemoteOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)
        self._remote: Remote | None = self._config_entry.runtime_data.remote
        self._bypass_steps: bool = False

    async def async_connect_remote(self) -> None:
        """Connect and initialize the remote for the options flow."""
        self._remote = Remote(
            self._config_entry.data["host"],
            pin=self._config_entry.data["pin"],
            api_key=self._config_entry.data["apiKey"],
        )
        await self._remote.validate_connection()
        await self._remote.init()

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        try:
            await self._remote.validate_connection()
        except Exception:
            return await self.async_step_remote_host(final_step=True)

        if self._remote.system.flags.external_entity_configuration_available:
            return self.async_show_menu(
                step_id="init",
                menu_options=["select_entities", "activities", "remote_host"],
                description_placeholders={"remote": self._remote.device.name},
            )
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
                        default=self._config_entry.options.get(
                            CONF_ACTIVITIES_AS_SWITCHES, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SUPPRESS_ACTIVITIY_GROUPS,
                        default=self._config_entry.options.get(
                            CONF_SUPPRESS_ACTIVITIY_GROUPS, False
                        ),
                    ): bool,
                }
            ),
            last_step=False,
        )

    async def async_step_media_player(self, user_input=None) -> FlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_remote()

        return self.async_show_form(
            step_id="media_player",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_GLOBAL_MEDIA_ENTITY,
                        default=self._config_entry.options.get(
                            CONF_GLOBAL_MEDIA_ENTITY, True
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
                        default=self._config_entry.options.get(
                            CONF_ACTIVITY_GROUP_MEDIA_ENTITIES, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ACTIVITY_MEDIA_ENTITIES,
                        default=self._config_entry.options.get(
                            CONF_ACTIVITY_MEDIA_ENTITIES, False
                        ),
                    ): bool,
                }
            ),
            last_step=False,
        )

    async def async_step_remote(self, user_input=None):
        """Handle options step two flow initialized by the user."""
        activity_list = ["No Action"]
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        for activity in self._remote.activities:
            activity_list.append(activity.name)

        return self.async_show_form(
            step_id="remote",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        REMOTE_ON_BEHAVIOR,
                        default=self._config_entry.options.get(
                            REMOTE_ON_BEHAVIOR, "No Action"
                        ),
                    ): vol.In(activity_list),
                }
            ),
            last_step=True,
        )

    async def async_step_remote_host(
        self, user_input=None, final_step: bool = False
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        if final_step is True:
            self._bypass_steps = True

        next_step = None
        if (
            self._remote.system.flags.external_entity_configuration_available
            and self._bypass_steps is False
        ):
            next_step = self.async_step_websocket

        return await async_step_remote_host(
            self,
            self.hass,
            self._remote,
            self._config_entry,
            self._update_options,
            user_input,
            step_id="remote_host",
            next_step_callback=next_step,
        )

    async def async_step_websocket(self, user_input=None):
        """Handle a flow initialized by the user."""
        return await async_step_websocket(
            self,
            self.hass,
            self._remote,
            self._update_options,
            user_input,
            step_id="websocket",
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)

    async def async_step_select_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selected entities to subscribe to."""

        return await async_step_select_entities(
            self,
            self._remote,
            self.async_step_finish,
            user_input,
        )

    async def async_step_fix_ws(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fix WebSocket URL Step"""
        return await async_step_fix_ws(
            self,
            self.hass,
            self._remote,
            self.async_step_finish,
            user_input,
        )

    async def async_step_finish(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish Step"""
        return await self._update_options()


# Shared flow adapters accept Home Assistant context and callbacks explicitly.
# pylint: disable=too-many-arguments,too-many-positional-arguments
async def async_step_remote_host(
    config_flow: UnfoldedCircleRemoteConfigFlow
    | UnfoldedCircleRemoteOptionsFlowHandler,
    hass: HomeAssistant,
    remote: Remote,
    config_entry: ConfigEntry,
    finish_callback: Callable[..., Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
    step_id: str = "remote_host",
    next_step_callback: Callable[..., Awaitable[FlowResult]] | None = None,
) -> FlowResult:
    """Shared function for updating remote host."""
    errors: dict[str, str] = {}

    if user_input is not None:
        remote_api = Remote(
            api_url=user_input.get("host"),
            api_key=config_entry.data["apiKey"],
        )
        try:
            if await remote_api.validate_connection():
                data = config_entry.data.copy()
                _LOGGER.debug("Updating host for remote")
                data["host"] = remote_api.endpoint
                hass.config_entries.async_update_entry(config_entry, data=data)
                config_flow.options[CONF_DIRECT_DOCK_COMMUNICATION] = user_input.get(
                    CONF_DIRECT_DOCK_COMMUNICATION,
                    config_flow.options.get(CONF_DIRECT_DOCK_COMMUNICATION, False),
                )
                options = dict(config_entry.options)
                options[CONF_DIRECT_DOCK_COMMUNICATION] = user_input.get(
                    CONF_DIRECT_DOCK_COMMUNICATION,
                    options.get(CONF_DIRECT_DOCK_COMMUNICATION, False),
                )
                hass.config_entries.async_update_entry(config_entry, options=options)
        except ClientConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception during host update")
            errors["base"] = "unknown"
        else:
            if next_step_callback is not None:
                return await next_step_callback()
            return await finish_callback()

    last_step = next_step_callback is None

    return config_flow.async_show_form(
        step_id=step_id,
        data_schema=vol.Schema(
            {
                vol.Required(
                    "host",
                    default=config_entry.data["host"],
                ): str,
                vol.Optional(
                    CONF_DIRECT_DOCK_COMMUNICATION,
                    default=config_entry.options.get(
                        CONF_DIRECT_DOCK_COMMUNICATION, False
                    ),
                ): bool,
            }
        ),
        description_placeholders={"name": remote.device.name if remote else "Remote"},
        last_step=last_step,
        errors=errors,
    )


async def async_step_websocket(
    config_flow: UnfoldedCircleRemoteConfigFlow
    | UnfoldedCircleRemoteOptionsFlowHandler,
    hass: HomeAssistant,
    remote: Remote,
    finish_callback: Callable[..., Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
    step_id: str = "websocket",
) -> FlowResult:
    """Shared function for updating websocket URL."""
    errors: dict[str, str] = {}

    if user_input is not None:
        try:
            await validate_and_register_system_and_driver(
                remote,
                hass,
                user_input.get("websocket_url"),
            )
        except InvalidWebsocketAddress as ex:
            _LOGGER.error("Invalid Websocket Address: %s", ex)
            errors["base"] = "invalid_websocket_address"
        except TokenRegistrationError as ex:
            _LOGGER.error("Error during token registration on remote: %s", ex)
            errors["base"] = "ha_driver_failure"
        except UnableToDetermineUser as ex:
            _LOGGER.error("Error determining Home Assistant user: %s", ex)
            errors["base"] = "user_determination"
        except Exception as ex:
            _LOGGER.error(
                "Error during driver registration, continue config flow: %s",
                ex,
            )
        else:
            if hasattr(config_flow, "options") and config_flow.options is not None:
                config_flow.options.update(user_input)
            return await finish_callback()

    url = await get_registered_websocket_url(remote)
    if url is None:
        url = get_ha_websocket_url(hass)
    if user_input is not None:
        url = user_input.get("websocket_url")

    return config_flow.async_show_form(
        step_id=step_id,
        data_schema=vol.Schema(
            {
                vol.Required(
                    "websocket_url",
                    default=url,
                ): str,
            }
        ),
        last_step=True,
        errors=errors,
    )


async def async_step_fix_ws(
    config_flow: UnfoldedCircleRemoteConfigFlow
    | UnfoldedCircleRemoteOptionsFlowHandler,
    hass: HomeAssistant,
    remote: Remote,
    finish_callback: Callable[[dict[str, Any] | None], Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
) -> FlowResult:
    """Fix WebSocket URL Step"""
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            await validate_and_register_system_and_driver(
                remote,
                hass,
                user_input.get("websocket_url"),
            )
        except InvalidWebsocketAddress as ex:
            _LOGGER.error("Invalid Websocket Address: %s", ex)
            errors["base"] = "invalid_websocket_address"
        except Exception as ex:
            _LOGGER.error("Error during driver registration: %s", ex)
            errors["base"] = "ha_driver_failure"
        else:
            config_flow.options.update(user_input)
            return await finish_callback()

    url = await get_registered_websocket_url(remote)
    if url is None:
        url = get_ha_websocket_url(hass)
    if user_input is not None:
        url = user_input.get("websocket_url")

    return config_flow.async_show_form(
        step_id="fix_ws",
        data_schema=vol.Schema(
            {
                vol.Required(
                    "websocket_url",
                    default=url,
                ): str,
            }
        ),
        last_step=True,
        errors=errors,
    )


# This flow deliberately keeps its intermediate values explicit for readability.
# pylint: disable=too-many-locals
async def async_step_select_entities(
    config_flow: UnfoldedCircleRemoteConfigFlow
    | UnfoldedCircleRemoteOptionsFlowHandler,
    remote: Remote,
    finish_callback: Callable[[dict[str, Any] | None], Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
) -> FlowResult:
    """Select entities through the Remote HA websocket subscription."""
    errors: dict[str, str] = {}
    saved_entities = list(
        getattr(config_flow, "options", {}).get("available_entities", [])
    )
    client_id = getattr(config_flow, "options", {}).get(
        "client_id", remote.device.hostname
    )
    subscribed_entities: list[str] = []
    configuration_subscription = None
    integration_id = ""
    websocket_client = UCWebsocketClient(config_flow.hass)

    try:
        integration_id = await connect_integration(remote)
        (
            entity_subscription,
            configuration_subscription,
        ) = await websocket_client.async_wait_for_subscriptions(client_id)
        client_id = configuration_subscription.client_id
        subscribed_entities = entity_subscription.entity_ids
    except Exception as ex:
        _LOGGER.warning(
            "Unable to establish HA websocket subscriptions for %s: %s",
            remote.device.name,
            ex,
        )
        errors["base"] = "ha_driver_failure"

    configured_entities = list(dict.fromkeys([*subscribed_entities, *saved_entities]))

    if user_input is not None and configuration_subscription is not None:
        selected_entities = user_input.get("add_entities", [])
        final_entities = list(dict.fromkeys([*configured_entities, *selected_entities]))
        entity_states = [
            state
            for entity_id in final_entities
            if (state := config_flow.hass.states.get(entity_id)) is not None
        ]

        if await websocket_client.send_configuration_to_remote(
            client_id, entity_states
        ):
            config_flow.options["available_entities"] = final_entities
            config_flow.options["client_id"] = client_id
            return await finish_callback(None)

        _LOGGER.error(
            "Failed to notify remote %s of selected entities", remote.device.name
        )
        errors["base"] = "ha_driver_failure"

    remote_ha_config_url = (
        f"{remote.configuration_url}#/integration/{integration_id}"
        if remote.system.flags.new_web_configurator
        else f"{remote.configuration_url.rstrip('/')}#/integrations-devices/{integration_id}"
    )
    add_selector: EntitySelectorConfig = {
        "exclude_entities": configured_entities,
        "filter": [{"domain": HA_SUPPORTED_DOMAINS}],
        "multiple": True,
    }
    schema: dict = {
        vol.Optional("add_entities", default=[]): EntitySelector(add_selector),
    }

    return config_flow.async_show_form(
        step_id="select_entities",
        data_schema=vol.Schema(schema),
        description_placeholders={
            "remote_name": remote.device.name,
            "remote_ha_config_url": remote_ha_config_url,
        },
        errors=errors,
    )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class InvalidDockPassword(HomeAssistantError):
    """Error to indicate an invalid dock password was supplied"""


class CannotCreateHAToken(HomeAssistantError):
    """Error to indicate there the creation of HA token failed."""
