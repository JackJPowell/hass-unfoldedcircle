"""Config flow for Unfolded Circle Remote integration."""

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any, Awaitable, Callable

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN, RefreshToken
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_ACTIVITIES_AS_SWITCHES,
    CONF_ACTIVITY_GROUP_MEDIA_ENTITIES,
    CONF_ACTIVITY_MEDIA_ENTITIES,
    CONF_GLOBAL_MEDIA_ENTITY,
    CONF_SERIAL,
    CONF_SUPPRESS_ACTIVITIY_GROUPS,
    DOMAIN,
    HA_SUPPORTED_DOMAINS, UC_HA_TOKEN_ID, UC_HA_SYSTEM, UC_HA_DRIVER_ID
)
from .pyUnfoldedCircleRemote.const import AUTH_APIKEY_NAME, SIMULATOR_MAC_ADDRESS
from .pyUnfoldedCircleRemote.remote import AuthenticationError, Remote
from .websocket import SubscriptionEvent, UCWebsocketClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required("host"): str, vol.Required("pin"): str}
)

STEP_ZEROCONF_DATA_SCHEMA = vol.Schema({vol.Required("pin"): str})


async def generate_token(hass: HomeAssistant, name):
    """Generate a token for Unfolded Circle to use with HA API"""
    user = await hass.auth.async_get_owner()
    try:
        token: RefreshToken | None = None
        if user.refresh_tokens:
            for refresh_token in user.refresh_tokens.values():
                if refresh_token.client_name == name:
                    token = refresh_token
                    break
        if not token:
            token = await hass.auth.async_create_refresh_token(
                user=user,
                client_name=name,
                token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
                access_token_expiration=timedelta(days=3652),
            )
    except ValueError:
        _LOGGER.warning("There is already a long lived token with %s name", name)

        return None
    return hass.auth.async_create_access_token(token)


async def remove_token(hass: HomeAssistant, token):
    _LOGGER.debug("Removing refresh token")
    refresh_token = hass.auth.async_get_refresh_token_by_token(token)
    hass.auth.async_remove_refresh_token(refresh_token)


async def async_step_select_entities(
    config_flow: ConfigFlow | config_entries.OptionsFlow,
    hass: HomeAssistant,
    remote: Remote,
    finish_callback: Callable[[dict[str, Any] | None], Awaitable[FlowResult]],
    user_input: dict[str, Any] | None = None,
) -> FlowResult:
    """Handle the selected entities to subscribe to for both setup and config flows."""
    errors: dict[str, str] = {}
    subscribed_entities_subscription: SubscriptionEvent | None = None
    configure_entities_subscription: SubscriptionEvent | None = None
    websocket_client = UCWebsocketClient(hass)
    filtered_domains = HA_SUPPORTED_DOMAINS
    _LOGGER.debug("Extracted remote information %s", await remote.get_version())
    _LOGGER.debug("Using remote ID \"%s\" to get and set subscribed entities", remote.hostname)

    if user_input is None:
        # First find the active HA drivers on the remote
        integrations = await remote.get_remote_integrations()
        _LOGGER.debug("Extraction of remote's integrations %s", integrations)
        for integration in integrations:
            integration_id: str | None = integration.get("integration_id", None)
            if integration_id is None: # or not integration.get("enabled", False):
                continue
            # TODO hack to reload only HA integrations including external ones
            if not integration_id.startswith(UC_HA_DRIVER_ID):
                continue
            # Force reload of all the integrations entities as we don't know which one to address
            _LOGGER.debug("Refresh the integration entities of %s : %s", integration_id,
                          await remote.get_remote_integration_entities(integration_id, True))

        # Wait until 5 seconds so that the driver connects to HA and subscribe to events
        retries = 5
        while retries > 0:
            await asyncio.sleep(1)
            retries -= 1
            subscribed_entities_subscription = websocket_client.get_subscribed_entities(remote.hostname)
            configure_entities_subscription = websocket_client.get_driver_subscription(remote.hostname)
            if subscribed_entities_subscription is not None and configure_entities_subscription is not None:
                break
            _LOGGER.debug("Waiting for current subscribed entities from HA driver... (%s)", retries)

        if configure_entities_subscription is None:
            _LOGGER.error(
                "The remote's websocket didn't subscribe to configuration event, "
                "unable to retrieve and update entities"
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options={
                    "select_entities": "Remote is not connected, retry",
                    "finish": "Ignore this step and finish",
                },
            )
        _LOGGER.debug("Found configuration subscription for remote : %s", configure_entities_subscription)
        subscribed_entities: list[str] = []
        if subscribed_entities_subscription:
            _LOGGER.debug("Found subscribed entities for remote : %s", subscribed_entities_subscription)
            subscribed_entities = subscribed_entities_subscription.entity_ids

        config: EntitySelectorConfig = {
            "exclude_entities": subscribed_entities,
            "filter": [{"domain": filtered_domains}],
            "multiple": True,
        }

        data_schema: dict[any, any] = {"add_entities": EntitySelector(config)}
        if len(subscribed_entities) > 0:
            config: EntitySelectorConfig = {
                "include_entities": subscribed_entities,
                "filter": [{"domain": filtered_domains}],
                "multiple": True,
            }
            data_schema.update({"remove_entities": EntitySelector(config)})

        _LOGGER.debug("Add/removal of entities %s", data_schema)
        return config_flow.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )
    if user_input is not None:
        configure_entities_subscription = websocket_client.get_driver_subscription(remote.hostname)
        subscribed_entities_subscription = websocket_client.get_subscribed_entities(remote.hostname)
        if configure_entities_subscription is None:
            _LOGGER.error(
                "The remote's websocket didn't subscribe to configuration event, "
                "unable to retrieve and update entities"
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options={
                    "select_entities": "Remote is not connected, retry",
                    "finish": "Ignore this step and finish",
                },
            )
        subscribed_entities: list[str] = []
        if subscribed_entities_subscription:
            _LOGGER.debug("Found subscribed entities for remote : %s", subscribed_entities_subscription)
            subscribed_entities = subscribed_entities_subscription.entity_ids

        add_entities = user_input.get("add_entities", [])
        remove_entities = user_input.get("remove_entities", [])
        final_list = set(subscribed_entities) - set(remove_entities)
        final_list.update(add_entities)
        final_list = list(final_list)

        _LOGGER.debug(
            "Selected entities to subscribe to : add %s, remove %s => %s",
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
            result = await websocket_client.send_configuration_to_remote(remote.hostname, entity_states)
            if not result:
                _LOGGER.error(
                    "Failed to notify remote with the new entities %s",
                    remote.hostname,
                )
                return config_flow.async_show_menu(
                    step_id="select_entities",
                    menu_options={
                        "select_entities": "Try again",
                        "finish": "Ignore this step and finish",
                    },
                )
            # Subscribe to the new entities
            integrations = await remote.get_remote_integrations()
            for integration in integrations:
                integration_id = integration.get("integration_id", None)
                if (
                    integration_id is None
                    or integration.get("driver_id", "") != subscribed_entities_subscription.driver_id
                ):
                    continue
                await remote.get_remote_integration_entities(integration_id, True)
                await asyncio.sleep(3)
                # Subscribe to all available entities sent before
                await remote.set_remote_integration_entities(integration_id, [])

        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.error(
                "Error while sending new entities to the remote %s (%s) %s",
                remote.ip_address,
                final_list,
                ex,
            )
            return config_flow.async_show_menu(
                step_id="select_entities",
                menu_options={
                    "select_entities": "Try again",
                    "finish": "Ignore this step and finish",
                },
            )
        return await finish_callback(None)


class UnfoldedCircleRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Remote."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    reauth_entry: ConfigEntry | None = None

    def __init__(self) -> None:
        """Unfolded Circle Config Flow."""
        self.api_keyname: str | None = None
        self.discovery_info: dict[str, Any] = {}
        self._data = None
        self._remote: Remote | None = None
        self._websocket_client: UCWebsocketClient | None

    async def validate_input(self, data: dict[str, Any], host: str = "") -> dict[str, Any]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        self._websocket_client = UCWebsocketClient(self.hass)
        if host != "":
            self._remote = Remote(host, data["pin"])
        else:
            self._remote = Remote(data["host"], data["pin"])

        try:
            await self._remote.can_connect()
        except AuthenticationError as err:
            raise InvalidAuth from err
        except CannotConnect as ex:  # pylint: disable=broad-except
            raise CannotConnect from ex

        for key in await self._remote.get_api_keys():
            if key.get("name") == AUTH_APIKEY_NAME:
                await self._remote.revoke_api_key()

        url = get_url(self.hass)
        key = await self._remote.create_api_key()
        if not key:
            raise InvalidAuth("Unable to login: failed to create API key")
        await self._remote.get_remote_information()
        await self._remote.get_remote_configuration()
        await self._remote.get_remote_wifi_info()

        # If this part (register a new HA token and send it to the remote) fails, we should let the config flow continue
        # It will let have the remote entities inside HA, but it will not let configure the HA entities on the remote
        token = None
        try:
            token = await generate_token(self.hass, f"{self._remote.name}  ({self._remote.serial_number})")
            _LOGGER.debug("Generated token : %s", f"{self._remote.name}  ({self._remote.serial_number})")
            await self._remote.set_token_for_external_system(
                system=UC_HA_SYSTEM, token_id=UC_HA_TOKEN_ID, token=token, name="Home Assistant Access token",
                description="URL and long lived access token for Home Assistant WebSocket API",
                url=url, data=""
            )
            remote_drivers_instances = await self._remote.get_integrations()
            _LOGGER.debug("Remote list of integrations %s", remote_drivers_instances)
            try:
                ha_driver_instance = next(filter(lambda instance: instance.get('driver_id', None) == UC_HA_DRIVER_ID,
                                                 remote_drivers_instances))
                _LOGGER.debug("Home assistant driver instance found %s", ha_driver_instance)
            except StopIteration:
                _LOGGER.debug("No Home assistant driver instance (%s), create one", UC_HA_DRIVER_ID)
                await self._remote.create_driver_instance(UC_HA_DRIVER_ID, {
                    "name": {
                        "en": "Home Assistant"
                    },
                    "icon": "uc:hass",
                    "enabled": True
                })
        except Exception as ex:
            _LOGGER.error("Error during the driver registration to the remote %s, keep on config flow", ex)

        mac_address = None
        if self._remote.mac_address:
            mac_address = self._remote.mac_address.replace(":", "").lower()

        # Return info that you want to store in the config entry.
        return {
            "title": self._remote.name,
            "apiKey": key,
            "host": self._remote.endpoint,
            "pin": data["pin"],
            "mac_address": self._remote.mac_address,
            "ip_address": self._remote.ip_address,
            "token": token,
            "token_id": UC_HA_TOKEN_ID,
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
        hostname = discovery_info.hostname
        name = discovery_info.name
        endpoint = f"http://{host}:{port}/api/"
        # Best location to initialize websocket instance : it will run even if no integrations are configured
        self._websocket_client = UCWebsocketClient(self.hass)
        mac_address = None
        is_simulator = False
        # TODO : check RemoteThree regex see with @markus
        try:
            mac_address = (
                re.match(r"(?:RemoteTwo|RemoteThree)-(.*?)\.", hostname)
                .group(1)
                .lower()
            )
        except Exception:
            try:
                mac_address = (
                    re.match(r"(?:RemoteTwo|RemoteThree)-(.*?)\.", name)
                    .group(1)
                    .lower()
                )
            except Exception:
                if (
                    discovery_info.properties.get("model") != "UCR2-simulator"
                    and discovery_info.properties.get("model") != "UCR3-simulator"
                ):
                    return self.async_abort(reason="no_mac")
                _LOGGER.debug("Zeroconf from the Simulator %s", discovery_info)
                is_simulator = True
                mac_address = SIMULATOR_MAC_ADDRESS.replace(":", "").lower()

        remote_name = "Remote Two"
        if "RemoteThree" in hostname:
            remote_name = "Remote Three"
        self.discovery_info.update({
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_NAME: f"{remote_name} ({host})",
            CONF_MAC: mac_address,
        })

        _LOGGER.debug(
            "Unfolded circle remote found %s %s %s :", mac_address, host, discovery_info
        )

        # Use mac address as unique id as this is the only common
        # information between zeroconf and user conf
        if mac_address:
            await self._async_set_unique_id_and_abort_if_already_configured(mac_address)

        # Retrieve device friendly name set by the user
        device_name = remote_name
        try:
            response = await Remote.get_version_information(endpoint)
            device_name = response.get("device_name", None)
            if not device_name:
                device_name = remote_name
        except Exception:
            pass

        if is_simulator:
            device_name = f"{device_name} Simulator"

        self.context.update({
            "title_placeholders": {"name": device_name},
            "configuration_url": (
                f"http://{discovery_info.host}:{discovery_info.port}/configurator/"
            ),
            "product": "Product",
        })

        _LOGGER.debug(
            "Unfolded Circle Zeroconf Creating: %s %s", mac_address, discovery_info
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
            info = await self.validate_input(user_input, host)
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
            return self.async_create_entry(
                title=info.get("title"),
                data=info,
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=STEP_ZEROCONF_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        self._websocket_client = UCWebsocketClient(self.hass)
        errors: dict[str, str] = {}
        if user_input is None or user_input == {}:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        try:
            info = await self.validate_input(user_input, "")
            self._data = info
            self.discovery_info.update({CONF_MAC: info[CONF_MAC]})
            # Check unique ID here based on serial number
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
            return await self.async_step_select_entities(None)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
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
        self._websocket_client = UCWebsocketClient(self.hass)
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
            info = await self.validate_input(
                user_input, self.reauth_entry.data[CONF_HOST]
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

    async def async_step_select_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selected entities to subscribe to."""
        return await async_step_select_entities(
            self, self.hass, self._remote, self.async_step_finish, user_input
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_create_entry(title=self._data["title"], data=self._data)


class UnfoldedCircleRemoteOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Unfolded Circle Remote options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self._remote: Remote | None = None
        self._websocket_client: UCWebsocketClient | None
        self._entity_ids: list[str] | None = None

    async def async_connect_remote(self) -> any:
        self._remote = Remote(
            self.config_entry.data["host"],
            self.config_entry.data["pin"],
            self.config_entry.data["apiKey"],
        )
        await self._remote.can_connect()
        await self._remote.get_version()
        return await self._remote.get_remote_information()

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        self._websocket_client = UCWebsocketClient(self.hass)
        await self.async_connect_remote()
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "select_entities": "Configure the entities on the remote",
                "activities": "Configure the integration",
            },
        )

    async def async_step_media_player(self, user_input=None) -> FlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="media_player",
            data_schema=vol.Schema({
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
            }),
            last_step=True,
        )

    async def async_step_activities(self, user_input=None):
        """Handle options step two flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_media_player()

        return self.async_show_form(
            step_id="activities",
            data_schema=vol.Schema({
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
            }),
            last_step=False,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)

    async def async_step_select_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selected entities to subscribe to."""

        # If user asks to configure entities, the HA driver may not have been configured at all
        # so we need to regenerate the HA token and check for a HA driver instance and create it if none
        url = get_url(self.hass)
        token = await generate_token(self.hass, f"{self._remote.name}  ({self._remote.serial_number})")
        _LOGGER.debug("Generated token : %s", f"{self._remote.name}  ({self._remote.serial_number})")
        try:
            await self._remote.set_token_for_external_system(
                system=UC_HA_SYSTEM, token_id=UC_HA_TOKEN_ID, token=token, name="Home Assistant Access token",
                description="URL and long lived access token for Home Assistant WebSocket API",
                url=url, data=""
            )
        except Exception as ex:
            _LOGGER.error("Error during token registration %s", ex)
            raise CannotConnect from ex
        try:
            remote_drivers_instances = await self._remote.get_integrations()
            _LOGGER.debug("Remote list of integrations %s", remote_drivers_instances)
            try:
                ha_driver_instance = next(filter(lambda instance: instance.get('driver_id', None) == UC_HA_DRIVER_ID,
                                          remote_drivers_instances))
                _LOGGER.debug("Home assistant driver instance found %s", ha_driver_instance)
            except StopIteration:
                _LOGGER.debug("No Home assistant driver instance (%s), create one", UC_HA_DRIVER_ID)
                await self._remote.create_driver_instance(UC_HA_DRIVER_ID, {
                    "name": {
                        "en": "Home Assistant"
                    },
                    "icon": "uc:hass",
                    "enabled": True
                })
        except Exception as ex:
            _LOGGER.error("Error during driver registration %s", ex)
            raise CannotConnect from ex

        return await async_step_select_entities(
            self, self.hass, self._remote, self.async_step_finish, user_input
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._update_options()


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
