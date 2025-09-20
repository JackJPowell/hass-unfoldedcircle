"""Config flow for Unfolded Circle Remote integration."""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Type

from aiohttp import ClientConnectionError
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
    CONF_GLOBAL_MEDIA_ENTITY,
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
    HA_SUPPORTED_DOMAINS,
    REMOTE_ON_BEHAVIOR,
)
from .helpers import (
    IntegrationNotFound,
    InvalidWebsocketAddress,
    UnableToDetermineUser,
    connect_integration,
    device_info_from_discovery_info,
    get_ha_websocket_url,
    get_registered_websocket_url,
    validate_and_register_system_and_driver,
    validate_websocket_address,
)
from pyUnfoldedCircleRemote.const import AUTH_APIKEY_NAME
from pyUnfoldedCircleRemote.remote import (
    ApiKeyCreateError,
    ApiKeyRevokeError,
    AuthenticationError,
    ExternalSystemAlreadyRegistered,
    Remote,
    RemoteConnectionError,
    TokenRegistrationError,
)
from .websocket import SubscriptionEvent, UCWebsocketClient

_LOGGER = logging.getLogger(__name__)
CONF_DOCK_ID = "dock_id"
CONF_SERIAL = "serial"
CONF_HA_WEBSOCKET_URL = "ha_ws_url"


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    reauth_entry: ConfigEntry | None = None

    def __init__(self) -> None:
        """Unfolded Circle Config Flow."""
        self.api_keyname: str | None = None
        self.discovery_info: dict[str, Any] = {}
        self._remote: Remote | None = None
        self.dock_count: int = 0
        self.info: dict[str, any] = {}
        self.options: dict[str, any] = {}

    async def validate_input(
        self, data: dict[str, Any], host: str = ""
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.
        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        if host != "":
            self._remote = Remote(host, data["pin"])
        else:
            self._remote = Remote(data["host"], data["pin"])

        websocket_url = data.get(CONF_HA_WEBSOCKET_URL, get_ha_websocket_url(self.hass))
        validate_websocket_address(websocket_url)

        try:
            await self._remote.validate_connection()
            _LOGGER.debug("Connection successful to %s", self._remote.endpoint)
        except AuthenticationError as err:
            raise InvalidAuth from err
        except RemoteConnectionError as ex:  # pylint: disable=broad-except
            raise CannotConnect from ex
        except ConnectionError as ex:
            raise CannotConnect from ex

        try:
            key = await self._remote.create_api_key_revoke_if_exists(AUTH_APIKEY_NAME)
        except ApiKeyRevokeError as ex:
            _LOGGER.error("Could not revoke existing API key: %s", ex)
        except ApiKeyCreateError as ex:
            _LOGGER.error("Could not create an API key on the remote: %s", ex)

        if not key:
            raise InvalidAuth("Unable to login: failed to create API key")
        _LOGGER.debug("Remote registered successfully, retrieving information...")

        try:
            await self._remote.get_version()
            await self._remote.get_remote_information()
            await self._remote.get_remote_configuration()
            await self._remote.get_remote_wifi_info()
            await self._remote.get_docks()
        except Exception as ex:
            _LOGGER.error("Error during extraction of remote information: %s", ex)

        # Call helper to register a new external system with the remote if needed
        if self._remote.external_entity_configuration_available:
            try:
                await validate_and_register_system_and_driver(
                    self._remote,
                    self.hass,
                    websocket_url,
                )
            except ExternalSystemAlreadyRegistered as ex:
                _LOGGER.debug("External system already registered %s", ex)
            except TokenRegistrationError as ex:
                _LOGGER.error("Error during external system registration %s", ex)
            except InvalidWebsocketAddress as ex:
                _LOGGER.error("Invalid websocket address supplied %s", ex)
            except Exception as ex:
                _LOGGER.error(
                    "Error during driver registration, continue config flow: %s", ex
                )

        mac_address = None
        if self._remote.mac_address:
            mac_address = self._remote.mac_address.replace(":", "").lower()

        docks = []
        for dock in self._remote.docks:
            docks.append({"id": dock.id, "name": dock.name, "password": ""})

        return {
            "title": self._remote.name,
            "apiKey": key,
            "host": self._remote.endpoint,
            "pin": data["pin"],
            "mac_address": self._remote.mac_address,
            "ip_address": self._remote.ip_address,
            CONF_SERIAL: self._remote.serial_number,
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
        port = discovery_info.port
        model = discovery_info.properties.get("model")

        (
            device_name,
            configuration_url,
            mac_address,
        ) = await device_info_from_discovery_info(discovery_info)
        remote_name = Remote.name_from_model_id(model)
        self.discovery_info.update(
            {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_NAME: f"{remote_name} ({host})",
                CONF_MAC: mac_address,
            }
        )

        _LOGGER.debug("Unfolded circle remote found %s :", discovery_info)
        if not mac_address:
            return self.async_abort(reason="no_mac")
        await self._async_set_unique_id_and_abort_if_already_configured(mac_address)

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
        zero_config_data_schema: dict[Required | Optional, Type] = vol.Schema(
            {
                vol.Required("pin"): str,
                vol.Optional(
                    CONF_HA_WEBSOCKET_URL, default=get_ha_websocket_url(self.hass)
                ): str,
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
            if self._remote.external_entity_configuration_available:
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
            schema: dict[Required | Optional, Type] = vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("pin"): str,
                    vol.Optional(
                        CONF_HA_WEBSOCKET_URL, default=get_ha_websocket_url(self.hass)
                    ): str,
                }
            )
            return self.async_show_form(
                step_id="user", data_schema=schema, errors=errors
            )

        try:
            _LOGGER.debug("Connect with manual input: %s", user_input)
            self.info = await self.validate_input(user_input, "")
            self.discovery_info.update({CONF_MAC: self.info[CONF_MAC]})
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
            if self._remote.external_entity_configuration_available:
                return await self.async_step_select_entities(None)
            return await self.async_step_finish(None)

        schema: dict[Required | Optional, Type] = vol.Schema(
            {
                vol.Required("host", default=user_input.get("host")): str,
                vol.Required("pin"): str,
                vol.Optional(
                    CONF_HA_WEBSOCKET_URL, default=user_input.get(CONF_HA_WEBSOCKET_URL)
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_set_unique_id_and_abort_if_already_configured(
        self, unique_id: str
    ) -> None:
        """Set the unique ID and abort if already configured."""
        index = unique_id.find("-")
        if index > 0:
            unique_id = unique_id[0:index]

        await self.async_set_unique_id(unique_id)
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
        zero_config_data_schema: dict[Required | Optional, Type] = vol.Schema(
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
            self.hass,
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
        self, user_input: dict[str, Any] | None = None
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
            if f"{self.config_entry.unique_id}_{dock.id}" not in configured_ids
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
                    if dock.id == user_input.get(CONF_DOCK_ID)
                ),
                None,
            )
            return await self.async_step_dock(
                user_input=None, dock_info=dock, first_call=True
            )

        if user_input is None or user_input == {}:
            for dock in available_docks:
                docks_to_display[dock.id] = dock.name

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
        placeholder = {"name": self.current_dock.name}

        if user_input is None or user_input == {}:
            if first_call is True:
                dock_data["id"] = self.current_dock.id
                dock_data["password"] = "0000"
                dock_data["name"] = self.current_dock.name
                # is_valid = await validate_dock_password(self.remote, dock_data)
                # if is_valid:
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

        if errors:
            return self.async_show_form(
                step_id="dock",
                data_schema=vol.Schema(schema),
                description_placeholders=placeholder,
                errors=errors,
                last_step=True,
            )
        data = {
            "id": dock_data["id"],
            "name": dock_data["name"],
            "password": dock_data["password"],
        }
        return self.async_create_entry(
            title=dock_data["name"],
            data=data,
            unique_id=f"{self.config_entry.unique_id}_{dock_data['id']}",
        )


class UnfoldedCircleRemoteOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)
        self._remote: Remote | None = self._config_entry.runtime_data.remote
        self._websocket_client: UCWebsocketClient | None = None
        self._entity_ids: list[str] | None = None
        self._bypass_steps: bool = False

    async def async_connect_remote(self) -> any:
        self._remote = Remote(
            self._config_entry.data["host"],
            self._config_entry.data["pin"],
            self._config_entry.data["apiKey"],
        )
        await self._remote.validate_connection()
        await self._remote.get_version()
        await self._remote.get_remote_configuration()
        return await self._remote.get_remote_information()

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        try:
            await self._remote.validate_connection()
        except Exception:
            return await self.async_step_remote_host(final_step=True)
        else:
            if self._remote.external_entity_configuration_available:
                return self.async_show_menu(
                    step_id="init",
                    menu_options=["select_entities", "activities", "remote_host"],
                    description_placeholders={"remote": self._remote.name},
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
        errors: dict[str, str] = {}
        if user_input is not None:
            existing_entry = self._config_entry

            remote_api = Remote(
                api_url=user_input.get("host"),
                apikey=existing_entry.data["apiKey"],
            )
            try:
                if await remote_api.validate_connection():
                    data = existing_entry.data.copy()
                    _LOGGER.debug("Updating host for remote")
                    data["host"] = remote_api.endpoint
            except ClientConnectionError:
                errors["base"] = "invalid_host"
            else:
                self.hass.config_entries.async_update_entry(existing_entry, data=data)

                if (
                    self._remote.external_entity_configuration_available
                    and self._bypass_steps is False
                ):
                    return await self.async_step_websocket()
                return await self._update_options()

        last_step = True
        if (
            self._remote.external_entity_configuration_available
            and self._bypass_steps is False
        ):
            last_step = False

        return self.async_show_form(
            step_id="remote_host",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "host",
                        default=self._config_entry.data["host"],
                    ): str,
                }
            ),
            description_placeholders={"name": self._remote.name},
            last_step=last_step,
            errors=errors,
        )

    async def async_step_websocket(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_and_register_system_and_driver(
                    self._remote,
                    self.hass,
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
                self.options.update(user_input)
                return await self._update_options()

        url = await get_registered_websocket_url(self._remote)
        if url is None:
            url = get_ha_websocket_url(self.hass)
        if user_input is not None:
            url = user_input.get("websocket_url")

        return self.async_show_form(
            step_id="websocket",
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

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)

    async def async_step_select_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selected entities to subscribe to."""

        return await async_step_select_entities(
            self,
            self.hass,
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
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish Step"""
        return await self._update_options()


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


async def async_step_select_entities(
    config_flow: UnfoldedCircleRemoteConfigFlow
    | UnfoldedCircleRemoteOptionsFlowHandler,
    hass: HomeAssistant,
    remote: Remote,
    finish_callback: Callable[[dict[str, Any] | None], Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
) -> FlowResult:
    """Retrieve and update the available entities to send to the remote for both setup and options flows."""
    errors: dict[str, str] = {}
    subscribed_entities_subscription: SubscriptionEvent | None = None
    configure_entities_subscription: SubscriptionEvent | None = None
    websocket_client = UCWebsocketClient(hass)
    _LOGGER.debug("Extracted remote information %s", await remote.get_version())
    _LOGGER.debug(
        'Using remote ID "%s" to get and set subscribed entities', remote.hostname
    )

    integration_id = await connect_integration(remote)
    if remote.new_web_configurator:
        remote_ha_config_url = (
            f"{remote.configuration_url}#/integration/{integration_id}"
        )
    else:
        remote_ha_config_url = f"{remote.configuration_url.rstrip('/')}#/integrations-devices/{integration_id}"

    websocket_url = await get_registered_websocket_url(remote)
    if websocket_url is None:
        websocket_url = get_ha_websocket_url(hass)

    # Prepare the list of entities to add/remove as available
    if user_input is None:
        integration_id = ""
        try:
            await remote.get_remote_configuration()
            integration_id = await validate_and_register_system_and_driver(
                remote, hass, websocket_url
            )
            _LOGGER.debug("Refresh the integration entities of %s", integration_id)
            integration_entities = await remote.get_remote_integration_entities(
                integration_id, True
            )
            _LOGGER.debug(
                "Integration entities of %s : %s", integration_id, integration_entities
            )
        except IntegrationNotFound:
            _LOGGER.error("Integration with name: %s not found", integration_id)
        except InvalidWebsocketAddress as ex:
            _LOGGER.error("Invalid websocket address supplied %s", ex)
        except Exception as ex:
            _LOGGER.warning(
                "Error while refreshing integration entities of integration: %s, %s",
                integration_id,
                ex,
            )
            errors["base"] = "ha_driver_failure"

        # Wait up to 5 seconds so that the driver connects to HA and subscribe to events
        retries = 5
        while retries > 0:
            retries -= 1
            try:
                subscribed_entities_subscription = (
                    websocket_client.get_subscribed_entities(remote.hostname)
                )
                configure_entities_subscription = (
                    websocket_client.get_driver_subscription(remote.hostname)
                )
                if (
                    subscribed_entities_subscription is not None
                    and configure_entities_subscription is not None
                ):
                    break
                _LOGGER.debug("Waiting for current subscribed entities: (%s)", retries)
            except Exception as ex:
                _LOGGER.error("Error while waiting for websocket events: %s", ex)
            await asyncio.sleep(1)

        if configure_entities_subscription is None:
            _LOGGER.error(
                "The remote's websocket didn't subscribe to configuration event, unable to retrieve and update entities"
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options=["fix_ws", "finish"],
                description_placeholders={"remote_ha_config_url": remote_ha_config_url},
            )
        _LOGGER.debug(
            "Found configuration subscription for remote %s (subscription_id %s) : entities %s",
            configure_entities_subscription.client_id,
            configure_entities_subscription.subscription_id,
            configure_entities_subscription.entity_ids,
        )
        subscribed_entities: list[str] = []
        if subscribed_entities_subscription:
            _LOGGER.debug(
                "Found subscribed entities for remote %s (subscription_id %s) : %s",
                subscribed_entities_subscription.client_id,
                subscribed_entities_subscription.subscription_id,
                subscribed_entities_subscription.entity_ids,
            )
            subscribed_entities = subscribed_entities_subscription.entity_ids

        # Initialize the available entities from : subscribed entities + available entities stored in config entry
        # (if any)
        available_entities = subscribed_entities.copy()

        # Only in option flow : retrieve configured available entities stored in the integration
        # and add them to the list if not present
        if (
            isinstance(config_flow, UnfoldedCircleRemoteOptionsFlowHandler)
            and config_flow.options
            and config_flow.options.get("available_entities", None)
        ):
            entities = config_flow.options["available_entities"]
            for entity_id in entities:
                if entity_id not in available_entities:
                    available_entities.append(entity_id)

        # Selector for entities to add (all except those already in the available list
        config: EntitySelectorConfig = {
            "exclude_entities": available_entities,
            "filter": [{"domain": HA_SUPPORTED_DOMAINS}],
            "multiple": True,
        }
        data_schema: dict[any, any] = {"add_entities": EntitySelector(config)}

        # Selector for entities to be removed from available list :
        # all in available list except those already subscribed which should be kept in the list
        # removable_list = available_entities.copy()
        # for entity_id in subscribed_entities:
        #     if entity_id in removable_list:
        #         removable_list.remove(entity_id)

        # if len(removable_list) > 0:
        #     config: EntitySelectorConfig = {
        #         "include_entities": removable_list,
        #         "filter": [{"domain": HA_SUPPORTED_DOMAINS}],
        #         "multiple": True,
        #     }
        #     data_schema.update({"remove_entities": EntitySelector(config)})

        data_schema.update({vol.Required("subscribe_entities", default=True): bool})

        _LOGGER.debug("Add/removal of entities %s", data_schema)

        return config_flow.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "remote_name": remote.name,
                "remote_ha_config_url": remote_ha_config_url,
            },
            errors=errors,
        )

    # When the user has selected entities to add/remove as available for the HA driver
    if user_input is not None:
        integration_id = await connect_integration(remote)

        configure_entities_subscription = websocket_client.get_driver_subscription(
            remote.hostname
        )
        subscribed_entities_subscription = websocket_client.get_subscribed_entities(
            remote.hostname
        )
        if configure_entities_subscription is None:
            _LOGGER.error(
                "The remote's websocket didn't subscribe to configuration event, unable to retrieve and update entities"
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options=["fix_ws", "finish"],
                description_placeholders={"remote_ha_config_url": remote_ha_config_url},
            )
        subscribed_entities: list[str] = []
        if subscribed_entities_subscription:
            _LOGGER.debug(
                "Found subscribed entities for remote : %s",
                subscribed_entities_subscription.entity_ids,
            )
            subscribed_entities = subscribed_entities_subscription.entity_ids

        add_entities = user_input.get("add_entities", [])
        remove_entities = user_input.get("remove_entities", [])
        do_subscribed_entities = user_input.get("subscribe_entities", True)

        final_list = set(subscribed_entities) - set(remove_entities)
        final_list.update(add_entities)
        final_list = list(final_list)

        _LOGGER.debug(
            "Selected entities to make available : add %s, remove %s => %s",
            add_entities,
            remove_entities,
            final_list,
        )

        entity_states = []
        for entity_id in final_list:
            state = hass.states.get(entity_id)
            if state is not None:
                entity_states.append(state)
        try:
            result = await websocket_client.send_configuration_to_remote(
                remote.hostname, entity_states
            )
            if not result:
                _LOGGER.error(
                    "Failed to notify remote with the new entities %s", remote.hostname
                )
                return config_flow.async_show_menu(
                    step_id="select_entities",
                    menu_options=["fix_ws", "finish"],
                    description_placeholders={
                        "remote_ha_config_url": remote_ha_config_url,
                    },
                )

            # Entities sent successfully to the HA driver, store the list in the registry
            if config_flow.options is None:
                config_flow.options = {}
            config_flow.options["available_entities"] = final_list
            if configure_entities_subscription:
                config_flow.options["client_id"] = (
                    subscribed_entities_subscription.client_id
                )

            # Subscribe to the new entities if requested by user
            if do_subscribed_entities:
                try:
                    integration_id = await connect_integration(
                        remote, subscribed_entities_subscription.driver_id
                    )
                    await remote.get_remote_integration_entities(integration_id, True)

                    await remote.set_remote_integration_entities(integration_id, [])
                    _LOGGER.debug(
                        "Entities registered successfully for: %s", integration_id
                    )
                except IntegrationNotFound:
                    _LOGGER.error(
                        "Failed to notify remote with the new entities %s for driver id %s",
                        remote.hostname,
                        subscribed_entities_subscription.driver_id,
                    )
                    return config_flow.async_show_menu(
                        step_id="select_entities",
                        menu_options=["fix_ws", "finish"],
                        description_placeholders={
                            "remote_ha_config_url": remote_ha_config_url,
                        },
                    )

        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.error(
                "Error while sending new entities to the remote %s (%s) %s",
                remote.ip_address,
                final_list,
                ex,
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options=["fix_ws", "finish"],
                description_placeholders={"remote_ha_config_url": remote_ha_config_url},
            )
        _LOGGER.debug("Entities registered successfully, finishing config flow")
        return await finish_callback(None)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class InvalidDockPassword(HomeAssistantError):
    """Error to indicate an invalid dock password was supplied"""


class CannotCreateHAToken(HomeAssistantError):
    """Error to indicate there the creation of HA token failed."""
