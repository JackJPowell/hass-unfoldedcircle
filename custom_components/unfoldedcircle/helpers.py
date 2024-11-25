"""Helper functions for Unfolded Circle Devices"""

import asyncio
from datetime import timedelta
import logging
import re
from urllib.parse import urljoin, urlparse

from pyUnfoldedCircleRemote.dock_websocket import DockWebsocket
from pyUnfoldedCircleRemote.remote import (
    HTTPError,
    IntegrationNotFound,
    Remote,
    TokenRegistrationError,
)

from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN, RefreshToken
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import UC_HA_SYSTEM, UC_HA_TOKEN_ID, DEFAULT_HASS_URL

_LOGGER = logging.getLogger(__name__)


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
    """Validate"""
    dock = remote_api.get_dock_by_id(user_info.get("id"))

    websocket = DockWebsocket(
        dock._ws_endpoint,
        api_key=dock.apikey,
        dock_password=user_info.get("password"),
    )
    try:
        return await asyncio.create_task(websocket.is_password_valid())
    except Exception as ex:
        _LOGGER.error("Error occurred when validating dock: %s %s", dock.name, ex)


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

    _LOGGER.debug("Gen. token for %s", name)
    return hass.auth.async_create_access_token(token)


async def remove_token(hass: HomeAssistant, token):
    """Remove api token from remote"""
    _LOGGER.debug("Removing refresh token")
    refresh_token = hass.auth.async_get_refresh_token_by_token(token)
    hass.auth.async_remove_refresh_token(refresh_token)


async def validate_and_register_system_and_driver(
    remote: Remote, hass: HomeAssistant, websocket_url
) -> str:
    """This method first tries to register the supplied external system and then
    creates the driver instance if one doesn't exist"""
    # Check if tokens exists
    integration_id = None
    if not await validate_tokens(hass, remote):
        try:
            # This commented block will prevent the creation of a new external token
            # if the user configured the remote manually. There is code in the hass
            # integration flow on the remote to switch to the ws-ha-api flow if present
            # ha_driver_instance = await remote.get_integration_instance_by_driver_id(
            #     UC_HA_SYSTEM
            # )
            # if ha_driver_instance.get("device_state", "") != "CONNECTED":
            if websocket_url == "" or websocket_url is None:
                websocket_url = get_ha_websocket_url(hass)

            token = await generate_token(hass, f"UCR:{remote.name}")
            await remote.set_token_for_external_system(
                system=UC_HA_SYSTEM,
                token_id=UC_HA_TOKEN_ID,
                token=token,
                name="Home Assistant Access token",
                description="URL and long lived access token for Home Assistant WebSocket API",
                url=websocket_url,
                data="",
            )
        except Exception as ex:
            _LOGGER.error("Error during token registration %s", ex)
            raise TokenRegistrationError from ex
    try:
        integration_id = await connect_integration(remote)
    except IntegrationNotFound:
        _LOGGER.debug(
            "No Home assistant driver instance (%s), create one",
            UC_HA_SYSTEM,
        )
        await remote.create_driver_instance(
            UC_HA_SYSTEM,
            {
                "name": {"en": "Home Assistant"},
                "icon": "uc:hass",
                "enabled": True,
            },
        )
        integration_id = await connect_integration(remote)
    except Exception as ex:
        _LOGGER.error("Error during driver registration %s", ex)

    return integration_id


async def connect_integration(remote: Remote, driver_id=UC_HA_SYSTEM) -> str:
    """Attempt to connect the Home Assistant Integration"""
    ha_driver_instance = await remote.get_integration_instance_by_driver_id(driver_id)
    _LOGGER.debug("Home assistant driver instance found %s", ha_driver_instance)
    # If the HA driver is disconnected, request connection in order to retrieve and update entities
    integration_id = ha_driver_instance.get("integration_id")
    if ha_driver_instance.get("device_state", "") != "CONNECTED":
        ha_driver = await remote.get_driver_instance(driver_id)
        if ha_driver.get("driver_state", "") == "IDLE":
            _LOGGER.debug("Home assistant driver has not started. Starting...")
            try:
                await remote.start_driver_by_id(driver_id)
                # Pull latest status
                ha_driver_instance = await remote.get_integration_instance_by_driver_id(
                    driver_id
                )
            except HTTPError as ex:
                _LOGGER.error("Error while trying to start remote and driver %s", ex)

        if ha_driver_instance.get("device_state", "") != "CONNECTED":
            try:
                await remote.put_integration(integration_id, command="CONNECT")
            except HTTPError as ex:
                _LOGGER.error("Error while trying to connect remote and driver %s", ex)
    return integration_id


@staticmethod
def mac_address_from_discovery_info(discovery_info: ZeroconfServiceInfo) -> str:
    """Returns the mac address embedded in the hostname. This is typically used with zeroconf broadcasts"""
    hostname = discovery_info.hostname
    name = discovery_info.name
    try:
        return re.match(r"(?:RemoteTwo|RemoteThree)-(.*?)\.", hostname).group(1).lower()
    except Exception:
        try:
            return re.match(r"(?:RemoteTwo|RemoteThree)-(.*?)\.", name).group(1).lower()
        except Exception:
            raise UnableToExtractMacAddress


async def device_info_from_discovery_info(discovery_info: ZeroconfServiceInfo) -> tuple:
    host = discovery_info.ip_address.compressed
    port = discovery_info.port
    model = discovery_info.properties.get("model")
    endpoint = f"http://{host}:{port}/api/"
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
        case "UCR3":
            device_name = "Remote 3"
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
        case "UCR3-simulator":
            device_name = "Remote 3 Simulator"
            configuration_url = (
                f"http://{discovery_info.host}:{discovery_info.port}/configurator/"
            )
    return device_name, configuration_url


async def validate_tokens(hass: HomeAssistant, remote: Remote) -> bool:
    """Validates the token in HA and the remote.
    This currently doesn't not validate the tokens are still valid,
    just that they exist."""
    refresh_token = None
    user = await hass.auth.async_get_owner()
    token: RefreshToken | None = None
    if user.refresh_tokens:
        for token in user.refresh_tokens.values():
            if token.client_name == f"UCR:{remote.name}":
                refresh_token = token
                break

    remote_has_token = await remote.external_system_has_token(UC_HA_SYSTEM)

    if not remote_has_token or not refresh_token:
        return False
    return True


class UnableToExtractMacAddress(Exception):
    """Raised when no mac address could be determined for given input."""
