"""Config flow for Unfolded Circle Remote integration."""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Type

from .pyUnfoldedCircleRemote.const import AUTH_APIKEY_NAME, SIMULATOR_MAC_ADDRESS
from .pyUnfoldedCircleRemote.remote import (
    ApiKeyCreateError,
    ApiKeyRevokeError,
    AuthenticationError,
    ExternalSystemAlreadyRegistered,
    ExternalSystemNotRegistered,
    Remote,
    RemoteConnectionError,
    TokenRegistrationError,
)
import voluptuous as vol
from voluptuous import Optional, Required

from homeassistant import config_entries
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_ACTIVITIES_AS_SWITCHES,
    CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
    CONF_ACTIVITY_MEDIA_ENTITIES,
    CONF_GLOBAL_MEDIA_ENTITY,
    CONF_HA_WEBSOCKET_URL,
    CONF_SERIAL,
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
    HA_SUPPORTED_DOMAINS,
)
from .helpers import (
    IntegrationNotFound,
    UnableToExtractMacAddress,
    InvalidWebsocketAddress,
    connect_integration,
    device_info_from_discovery_info,
    get_ha_websocket_url,
    get_registered_websocket_url,
    mac_address_from_discovery_info,
    synchronize_dock_password,
    validate_and_register_system_and_driver,
    register_system_and_driver,
    validate_dock_password,
    validate_websocket_address,
)
from .websocket import SubscriptionEvent, UCWebsocketClient

_LOGGER = logging.getLogger(__name__)


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    reauth_entry: ConfigEntry | None = None

    def __init__(self) -> None:
        """Unfolded Circle Config Flow."""
        self.api_keyname: str | None = None
        self.discovery_info: dict[str, Any] = {}
        self._remote: Remote | None = None
        self._websocket_client: UCWebsocketClient | None = None
        self.dock_count: int = 0
        self.info: dict[str, any] = {}

    async def validate_input(
        self, data: dict[str, Any], host: str = ""
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.
        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        self._websocket_client = UCWebsocketClient(self.hass)
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
            "docks": docks,
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
        # Best location to initialize websocket instance : it will run even if no integrations are configured
        self._websocket_client = UCWebsocketClient(self.hass)
        # TODO : check RemoteThree regex see with @markus
        try:
            mac_address = mac_address_from_discovery_info(discovery_info)
        except UnableToExtractMacAddress:
            if (
                discovery_info.properties.get("model") != "UCR2-simulator"
                and discovery_info.properties.get("model") != "UCR3-simulator"
            ):
                return self.async_abort(reason="no_mac")
            _LOGGER.debug("Zeroconf from the Simulator %s", discovery_info)
            mac_address = SIMULATOR_MAC_ADDRESS.replace(":", "").lower()

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
        # Use mac address as unique id
        if mac_address:
            await self._async_set_unique_id_and_abort_if_already_configured(mac_address)

        device_name, configuration_url = await device_info_from_discovery_info(
            discovery_info
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
            info = await self.validate_input(user_input, host)
            self.discovery_info.update({CONF_MAC: info[CONF_MAC]})
            await self._async_set_unique_id_and_abort_if_already_configured(
                info[CONF_MAC]
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
            if info["docks"]:
                return await self.async_step_dock(info=info, first_call=True)

            return self.async_create_entry(title=info["title"], data=info)

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=zero_config_data_schema,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        self._websocket_client = UCWebsocketClient(self.hass)
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
            info = await self.validate_input(user_input, "")
            self.info = info
            self.discovery_info.update({CONF_MAC: info[CONF_MAC]})
            await self._async_set_unique_id_and_abort_if_already_configured(
                info[CONF_MAC]
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
            if info["docks"]:
                return await self.async_step_dock(info=info, first_call=True)
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

    async def async_step_dock(
        self,
        user_input: dict[str, Any] | None = None,
        info: dict[str, any] = None,
        first_call: bool = False,
    ) -> FlowResult:
        """Called if there are docks associated with the remote"""
        schema = {}
        errors: dict[str, str] = {}
        dock_info: dict[str, any] | None = None
        placeholder: dict[str, any] | None = None
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
                        if self._remote.external_entity_configuration_available:
                            return await self.async_step_select_entities(None)
                        return await self.async_step_finish(None)

                return self.async_show_form(
                    step_id="dock",
                    data_schema=vol.Schema(schema),
                    description_placeholders=placeholder,
                    errors=errors,
                    last_step=True,
                )

        try:
            self.info["docks"][self.dock_count]["password"] = user_input["password"]
            is_valid = await validate_dock_password(self._remote, dock_info)
            if is_valid:
                self.dock_count += 1
                # Update other config entries where the same dock may be registered too
                # (same dock associated to multiple remotes)
                await synchronize_dock_password(self.hass, dock_info, "")
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
            if self._remote.external_entity_configuration_available:
                return await self.async_step_select_entities(None)
            return await self.async_step_finish(None)

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
        index = unique_id.find("-")
        if index > 0:
            unique_id = unique_id[0:index]

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
        self._websocket_client = UCWebsocketClient(self.hass)
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

            return self.async_create_entry(
                title=info["title"],
                data=info,
            )

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

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Complete conflig flow"""
        _LOGGER.debug("Create registry entry")
        try:
            result = self.async_create_entry(title=self.info["title"], data=self.info)
            _LOGGER.debug("Registry entry creation result : %s", result)
            return result
        except Exception as ex:
            _LOGGER.error("Error while creating registry entry %s", ex)
            raise ex

    async def async_step_error(
        self, user_input: dict[str, Any] | None = None, step="select_entities"
    ) -> FlowResult:
        match step:
            case "select_entities":
                return await async_step_select_entities(
                    self,
                    self.hass,
                    self._remote,
                    self.async_step_finish,
                    user_input,
                )


class UnfoldedCircleRemoteOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)
        self._remote: Remote | None = None
        self._websocket_client: UCWebsocketClient | None = None
        self._entity_ids: list[str] | None = None

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
        self._websocket_client = UCWebsocketClient(self.hass)
        await self.async_connect_remote()
        if self._remote.external_entity_configuration_available:
            return self.async_show_menu(
                step_id="init",
                menu_options=["select_entities", "activities"],
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
            if self._remote.external_entity_configuration_available:
                return await self.async_step_websocket()
            return await self._update_options()

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

    async def async_step_websocket(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if validate_websocket_address(user_input.get("websocket_url")):
                    try:
                        await register_system_and_driver(
                            self._remote,
                            self.hass,
                            user_input.get("websocket_url"),
                        )
                    except ExternalSystemNotRegistered as ex:
                        _LOGGER.debug(
                            "Error when registering the external system: %s", ex
                        )
                        errors["base"] = "ha_driver_failure"
                    except TokenRegistrationError as ex:
                        _LOGGER.error("Error during token creation: %s", ex)
                        errors["base"] = "ha_driver_failure"
                    except Exception as ex:
                        _LOGGER.error(
                            "Error during driver registration, continue config flow: %s",
                            ex,
                        )
                    else:
                        self.options.update(user_input)
                        return await self._update_options()
            except InvalidWebsocketAddress as ex:
                _LOGGER.error("Invalid Websocket Address: %s", ex)
                errors["base"] = "invalid_websocket_address"

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

    async def async_step_error(
        self, user_input: dict[str, Any] | None = None, step="select_entities"
    ) -> FlowResult:
        """Error Step"""
        try:
            await validate_and_register_system_and_driver(
                self._remote,
                self.hass,
                get_ha_websocket_url(self.hass),
            )
        except ExternalSystemNotRegistered as ex:
            _LOGGER.debug("Error when registering the external system: %s", ex)
        except TokenRegistrationError as ex:
            _LOGGER.error("Error during external system registration %s", ex)
        except InvalidWebsocketAddress as ex:
            _LOGGER.error("Invalid websocket address supplied %s", ex)
        except Exception as ex:
            _LOGGER.error(
                "Error during driver registration, continue config flow: %s", ex
            )
        match step:
            case "select_entities":
                return await async_step_select_entities(
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


async def async_step_select_entities(
    config_flow: UnfoldedCircleRemoteConfigFlow | UnfoldedCircleRemoteOptionsFlowHandler,
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
    filtered_domains = HA_SUPPORTED_DOMAINS
    _LOGGER.debug("Extracted remote information %s", await remote.get_version())
    _LOGGER.debug(
        'Using remote ID "%s" to get and set subscribed entities', remote.hostname
    )

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
                menu_options=["error", "finish"],
            )
        _LOGGER.debug(
            "Found configuration subscription for remote %s (subscription_id %s) : entities %s",
            configure_entities_subscription.client_id,
            configure_entities_subscription.subscription_id,
            configure_entities_subscription.entity_ids
        )
        subscribed_entities: list[str] = []
        if subscribed_entities_subscription:
            _LOGGER.debug(
                "Found subscribed entities for remote %s (subscription_id %s) : %s",
                subscribed_entities_subscription.client_id,
                subscribed_entities_subscription.subscription_id,
                subscribed_entities_subscription.entity_ids
            )
            subscribed_entities = subscribed_entities_subscription.entity_ids

        # Initialize the available entities from : subscribed entities + available entities stored in config entry
        # (if any)
        available_entities = subscribed_entities.copy()

        # Only in option flow : retrieve configured available entities stored in the integration
        # and add them to the list if not present
        if (isinstance(config_flow, UnfoldedCircleRemoteOptionsFlowHandler) and config_flow.options
                and config_flow.options.get("available_entities", None)):
            entities = config_flow.options["available_entities"]
            for entity_id in entities:
                if entity_id not in available_entities:
                    available_entities.append(entity_id)

        # Selector for entities to add (all except those already in the available list
        config: EntitySelectorConfig = {
            "exclude_entities": available_entities,
            "filter": [{"domain": filtered_domains}],
            "multiple": True,
        }
        data_schema: dict[any, any] = {"add_entities": EntitySelector(config)}

        # Selector for entities to be removed from available list :
        # all in available list except those already subscribed which should be kept in the list
        removable_list = available_entities.copy()
        for entity_id in subscribed_entities:
            if entity_id in removable_list:
                removable_list.remove(entity_id)

        if len(removable_list) > 0:
            config: EntitySelectorConfig = {
                "include_entities": removable_list,
                "filter": [{"domain": filtered_domains}],
                "multiple": True,
            }
            data_schema.update({"remove_entities": EntitySelector(config)})

        data_schema.update({vol.Required("subscribe_entities", default=True): bool})

        _LOGGER.debug("Add/removal of entities %s", data_schema)
        return config_flow.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(data_schema),
            description_placeholders={"remote_name": remote.name},
            errors=errors,
        )

    # When the user has selected entities to add/remove as available for the HA driver
    if user_input is not None:
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
                menu_options=["error", "finish"],
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
                    menu_options=["error", "finish"],
                )

            # Entities sent successfully to the HA driver, store the list in the registry
            # If Option flow
            if isinstance(config_flow, UnfoldedCircleRemoteOptionsFlowHandler) and config_flow.options:
                if config_flow.options is None:
                    config_flow.options = {}
                config_flow.options["available_entities"] = final_list
                if configure_entities_subscription:
                    config_flow.options["client_id"] = subscribed_entities_subscription.client_id
            elif isinstance(config_flow, UnfoldedCircleRemoteConfigFlow) and config_flow.info:
                if config_flow.info is None:
                    config_flow.info = {}
                config_flow.info["available_entities"] = final_list
                if configure_entities_subscription:
                    config_flow.info["client_id"] = subscribed_entities_subscription.client_id

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
                        menu_options=["error", "finish"],
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
                menu_options=["error", "finish"],
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
