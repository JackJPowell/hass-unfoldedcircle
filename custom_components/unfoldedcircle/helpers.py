"""Helper functions for Unfolded Circle Devices"""

import asyncio
from datetime import timedelta
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN, RefreshToken
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.exceptions import HomeAssistantError

from .const import COMMAND_LIST, DOMAIN, UC_HA_DRIVER_ID, UC_HA_SYSTEM, UC_HA_TOKEN_ID
from unfurled.remote import Remote
from unfurled.dock import Dock
from unfurled.helpers.exceptions import (
    EntityCommandError,
    HTTPError,
    IntegrationNotFound,
    InvalidButtonCommand,
    NoActivityRunning,
    RemoteIsSleeping,
    TokenRegistrationError,
)

_LOGGER = logging.getLogger(__name__)
DEFAULT_HASS_URL = "http://homeassistant.local:8123"


def get_ha_websocket_url(hass: HomeAssistant) -> str:
    """Return home assistant url else use default in const.py"""
    try:
        hass_url: str = get_url(hass)
    except NoURLAvailableError:
        hass_url = DEFAULT_HASS_URL
    except AttributeError:
        hass_url = DEFAULT_HASS_URL
    url = urlparse(hass_url)
    return urljoin(f"ws://{url.netloc}", "/api/websocket")


async def validate_dock_password(remote_api: Remote, user_info) -> bool:
    """Validate the dock password by attempting a short-lived WS connection."""
    dock = remote_api.find_dock(user_info.get("id"))
    if dock is None:
        _LOGGER.error("Dock %s not found on remote", user_info.get("id"))
        return False
    try:
        return await asyncio.wait_for(
            dock.validate_password(user_info.get("password", "")),
            timeout=10,
        )
    except Exception as ex:
        _LOGGER.error(
            "Error occurred when validating dock password for %s: %s",
            dock.device.name,
            ex,
        )
        return False


async def generate_token(hass: HomeAssistant, name):
    """Generate a token for Unfolded Circle to use with HA API"""
    user = await get_user(hass)

    if user is None:
        _LOGGER.error(
            "Make sure you are logged in with a user with administrative rights."
        )
        raise UnableToDetermineUser

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

    _LOGGER.debug("Gen. token for %s", name)
    return hass.auth.async_create_access_token(token)


async def get_user(hass: HomeAssistant) -> str:
    """Retrieve the currently logged-in user ID."""
    user = await hass.auth.async_get_owner()
    if user:
        return user

    users = await hass.auth.async_get_users()
    for user in users:
        if user.is_active and not user.system_generated and user.is_admin:
            return await hass.auth.async_get_user(user.id)

    return None


async def remove_token(hass: HomeAssistant, token):
    """Remove api token from remote"""
    _LOGGER.debug("Removing refresh token")
    refresh_token = hass.auth.async_get_refresh_token_by_token(token)
    if refresh_token:
        hass.auth.async_remove_refresh_token(refresh_token)
        return
    _LOGGER.info("Refresh token not found")


async def register_system_and_driver(
    remote: Remote, hass: HomeAssistant, websocket_url
) -> str:
    """Register remote system"""

    if not websocket_url:
        websocket_url = await get_registered_websocket_url(remote)
        if websocket_url is None:
            websocket_url = get_ha_websocket_url(hass)

    token = await generate_token(hass, f"UCR:{remote.device.name}")

    if token:
        try:
            await remote.auth.set_external_token(
                system=UC_HA_SYSTEM,
                token_id=UC_HA_TOKEN_ID,
                token=token,
                name="Home Assistant Access token",
                description="URL and long lived access token for Home Assistant WebSocket API",
                url=websocket_url,
            )
        except Exception as ex:
            _LOGGER.error("Error during token registration %s", ex)
            raise TokenRegistrationError from ex

    return await connect_integration(remote)


async def validate_and_register_system_and_driver(
    remote: Remote, hass: HomeAssistant, websocket_url: str | None
) -> str:
    """This method first tries to register the supplied external system and then
    creates the driver instance if one doesn't exist"""
    if validate_websocket_address(websocket_url):
        if not await validate_tokens(hass, remote):
            _LOGGER.debug("No valid external token, register one")
            return await register_system_and_driver(remote, hass, websocket_url)
        remote_websocket_url = await get_registered_websocket_url(remote)
        if remote_websocket_url != websocket_url:
            return await register_system_and_driver(remote, hass, websocket_url)
        return await connect_integration(remote, driver_id=UC_HA_DRIVER_ID)


async def connect_integration(remote: Remote, driver_id=UC_HA_DRIVER_ID) -> str:
    """Attempt to connect the Home Assistant Integration"""
    ha_driver_instance = {}
    try:
        _LOGGER.debug(
            "Home assistant driver integration lookup for system %s", driver_id
        )
        ha_driver_instance = await remote.integrations.get_by_driver(driver_id)
        _LOGGER.debug("Home assistant driver instance found %s", ha_driver_instance)
    except IntegrationNotFound:
        _LOGGER.debug(
            "No Home assistant driver instance (%s), create one",
            UC_HA_SYSTEM,
        )
        await remote.integrations.create_driver(
            UC_HA_SYSTEM,
            {
                "name": {"en": "Home Assistant"},
                "icon": "uc:hass",
                "enabled": True,
            },
        )
        ha_driver_instance = await remote.integrations.get_by_driver(driver_id)
    except Exception as ex:
        _LOGGER.error("Error during driver registration %s", ex)

    # If the HA driver is disconnected, request connection in order to retrieve and update entities
    integration_id = ha_driver_instance.get("integration_id")
    if ha_driver_instance.get("device_state", "") != "CONNECTED":
        ha_driver = await remote.integrations.get_driver(driver_id)
        if ha_driver.get("driver_state", "") == "IDLE":
            _LOGGER.debug("Home assistant driver has not started. Starting...")
            try:
                await remote.integrations.start_driver(driver_id)
                # Pull latest status
                ha_driver_instance = await remote.integrations.get_by_driver(driver_id)
            except HTTPError as ex:
                _LOGGER.error("Error while trying to start remote and driver %s", ex)

        if ha_driver_instance.get("device_state", "") != "CONNECTED":
            try:
                await remote.integrations.send_command(integration_id, "CONNECT")
            except HTTPError as ex:
                _LOGGER.error("Error while trying to connect remote and driver %s", ex)
    return integration_id


async def get_registered_websocket_url(remote: Remote) -> str:
    """Returns websocket url registered on remote"""
    try:
        external_systems = await remote.api.get_external_system(UC_HA_SYSTEM)
        if isinstance(external_systems, list):
            for ext in external_systems:
                if ext.get("token_id") == "ws-ha-api":
                    return ext.get("url", None)
        elif isinstance(external_systems, dict):
            if external_systems.get("token_id") == "ws-ha-api":
                return external_systems.get("url", None)
    except Exception:
        pass
    return None


async def device_info_from_discovery_info(discovery_info: ZeroconfServiceInfo) -> tuple:
    """Returns device information from zeroconf discovery info."""
    host = discovery_info.ip_address.compressed
    port = discovery_info.port
    model = discovery_info.properties.get("model", "")
    info = await Remote.resolve_discovery(host, port, model)
    return info["name"], info["configuration_url"], info["mac_address"]


async def validate_tokens(hass: HomeAssistant, remote: Remote) -> bool:
    """Validates the token in HA and the remote.
    This currently doesn't not validate the tokens are still valid,
    just that they exist."""
    refresh_token = None
    user = await hass.auth.async_get_owner()
    token: RefreshToken | None = None
    if user.refresh_tokens:
        for token in user.refresh_tokens.values():
            if token.client_name == f"UCR:{remote.device.name}":
                refresh_token = token
                break

    remote_has_token = await remote.auth.system_has_token(UC_HA_SYSTEM)

    if not remote_has_token or not refresh_token:
        return False
    return True


def validate_websocket_address(websocket_url: str | None) -> bool:
    """Validates the given url conforms to the home assistant web socket scheme"""
    if websocket_url:
        if re.match(r"^(ws|wss):\/\/.*\/api\/websocket", websocket_url):
            return True
    raise InvalidWebsocketAddress


async def synchronize_dock_password(
    hass: HomeAssistant, dock_info: dict[str, Any], entry_id: str
):
    """Synchronize the updated dock password to other integrations where the same dock is used"""
    existing_entries = hass.config_entries.async_entries(domain=DOMAIN)
    _LOGGER.debug(
        "Checking other config entries for dock registration: %s",
        ", ".join([entry.title for entry in existing_entries]),
    )
    for uc_entry in existing_entries:
        if (
            uc_entry.entry_id == entry_id
            or uc_entry.data is None
            or uc_entry.data.get("docks", None) is None
        ):
            continue
        for uc_dock in uc_entry.data["docks"]:
            if uc_dock["id"] == dock_info["id"]:
                _LOGGER.info(
                    "Found similar dock %s to update password for another remote %s",
                    uc_dock["id"],
                    uc_entry.title,
                )
                # Set the same password for the other dock entry and update the registry
                uc_dock["password"] = dock_info["password"]
                try:
                    hass.config_entries.async_update_entry(uc_entry, data=uc_entry.data)
                except Exception as ex:
                    _LOGGER.error(
                        "Error while trying to synchronize dock password on other remote %s",
                        ex,
                    )
                break


def update_config_entities(
    hass: HomeAssistant, client_id: str, entity_ids: list[str]
) -> list[str]:
    """Update registry entry of available entities configured in the remote if changed"""
    existing_entries = hass.config_entries.async_entries(domain=DOMAIN)
    try:
        config_entry = next(
            config_entry
            for config_entry in existing_entries
            if config_entry.options
            and config_entry.options.get("client_id", "") == client_id
        )
        if config_entry:
            _LOGGER.debug(
                "Unfolded circle get states from client %s, config entry found %s",
                client_id,
                config_entry.title,
            )
            available_entities = config_entry.options.get(
                "available_entities", []
            ).copy()
            update_needed = False
            for entity_id in entity_ids:
                if entity_id not in available_entities:
                    available_entities.append(entity_id)
                    update_needed = True
            if update_needed:
                options = dict(config_entry.options)
                options["available_entities"] = available_entities
                _LOGGER.debug(
                    "Available entities need to be updated in registry as there is a desync with the remote %s. Remote : %s, HA registry : %s",
                    client_id,
                    config_entry.options.get("available_entities", []),
                    available_entities,
                )
                hass.config_entries.async_update_entry(config_entry, options=options)
            return available_entities
        else:
            _LOGGER.debug(
                "Unfolded circle get states from client %s : no config entry", client_id
            )
            return []
    except StopIteration:
        _LOGGER.debug(
            "Unfolded circle get states from client %s : no config entry", client_id
        )
        return []


@callback
def async_create_issue_dock_password(
    hass: HomeAssistant, dock: Dock, entry, subentry
) -> None:
    """Create an issue in the issue registry for a dock with an empty password."""
    _LOGGER.debug("Empty dock password: %s", dock.device.name)
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        f"dock_password_{dock.device.id}",
        breaks_in_ha_version=None,
        data={
            "id": dock.device.id,
            "name": dock.device.name,
            "config_entry": entry,
            "subentry": subentry,
        },
        is_fixable=True,
        is_persistent=False,
        learn_more_url="https://github.com/jackjpowell/hass-unfoldedcircle",
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="dock_password",
        translation_placeholders={"name": dock.device.name},
    )


@callback
def async_create_issue_dock_unreachable(
    hass: HomeAssistant, dock: Dock, entry, subentry, error: str
) -> None:
    """Create an issue in the issue registry for an unreachable dock."""
    _LOGGER.warning("Dock unreachable: %s - %s", dock.device.name, error)
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        f"dock_unreachable_{dock.device.id}",
        breaks_in_ha_version=None,
        data={
            "id": dock.device.id,
            "name": dock.device.name,
            "config_entry": entry,
            "subentry": subentry,
        },
        is_fixable=False,
        is_persistent=False,
        learn_more_url="https://github.com/jackjpowell/hass-unfoldedcircle",
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="dock_unreachable",
        translation_placeholders={"name": dock.device.name, "error": str(error)},
    )


@callback
def async_delete_issue_dock_unreachable(hass: HomeAssistant, dock_id: str) -> None:
    """Delete the unreachable dock issue when dock becomes available."""
    issue_registry.async_delete_issue(hass, DOMAIN, f"dock_unreachable_{dock_id}")


@callback
def async_create_issue_websocket_connection(
    hass: HomeAssistant,
    entry,
    coordinator,
) -> None:
    """Create an issue in the issue registry for a websocket connection."""
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        "websocket_connection",
        breaks_in_ha_version=None,
        data={"config_entry": entry, "name": coordinator.api.device.name},
        is_fixable=True,
        is_persistent=False,
        learn_more_url="https://github.com/jackjpowell/hass-unfoldedcircle",
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key="websocket_connection",
        translation_placeholders={"name": coordinator.api.device.name},
    )


class Command:
    def __init__(
        self,
        coordinator,
        hass,
        data,
    ):
        self.coordinator = coordinator
        self.hass = hass
        self.data = data

    async def async_send(self, **kwargs):
        """Send a remote command."""
        commands: list[str] = []
        if type(self.data.get("command")) is list:
            commands = self.data.get("command")
        else:
            commands.append(self.data.get("command"))

        for indv_command in commands:
            if indv_command in COMMAND_LIST:
                if indv_command == "PAUSE":
                    indv_command = "PLAY"
                try:
                    await self.coordinator.api.send_button_command(
                        command=indv_command,
                        repeat=self.data.get("num_repeats"),
                        activity=self.data.get("activity"),
                        hold=self.data.get("hold"),
                        delay_secs=self.data.get("delay_secs"),
                    )
                except NoActivityRunning as err:
                    _LOGGER.error("No activity is running")
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="no_activity_running",
                    ) from err
                except InvalidButtonCommand as err:
                    _LOGGER.error("Invalid button command: %s", indv_command)
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="invalid_button_command",
                    ) from err
                except RemoteIsSleeping as err:
                    _LOGGER.error("The remote did not respond to the wake command")
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="remote_is_sleeping",
                    ) from err
                except EntityCommandError as err:
                    _LOGGER.error("Failed to send command: %s", err.message)
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="entity_command_error",
                    ) from err


class UnableToExtractMacAddress(Exception):
    """Raised when no mac address could be determined for given input."""


class InvalidWebsocketAddress(Exception):
    """Raised when an invalid websocket url is supplied"""


class UnableToDetermineUser(Exception):
    """Raised when the system can not determine the running user"""
