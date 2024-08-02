"""Custom websocket commands --
Implements the necessary methods called through HA websocket for the UC HA integration."""

import logging

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR

_LOGGER = logging.getLogger(__name__)

INFO_SCHEMA = {
    vol.Required("type"): f"{DOMAIN}/info",
    vol.Optional("message", description="Any String"): str,
    vol.Optional("data", description="Any Dict"): dict[any, any],
}


class UCClientInterface:
    """Unfolded Circle interface to handle remote requests"""

    def subscribe_entities_events(
        self, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Method called by the HA websocket component
        when a remote requests to subscribe to entity events."""


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register network websocket commands."""
    websocket_api.async_register_command(hass, ws_get_info)
    websocket_api.async_register_command(
        hass,
        ws_subscribe_event,
    )
    websocket_api.async_register_command(hass, ws_unsubscribe_event)


@websocket_api.websocket_command(INFO_SCHEMA)
@callback
def ws_get_info(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get info command."""

    _LOGGER.debug("Unfolded Circle connect request %s", msg)
    connection.send_message({
        "id": msg.get("id"),
        "type": "result",
        "success": True,
        "result": {"state": "CONNECTED", "cat": "DEVICE", "version": "1.0.0"},
        "message": msg.get("message"),
        "data": msg.get("data"),
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/event/unsubscribe",
})
@callback
def ws_unsubscribe_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Subscribe to incoming and outgoing events."""
    if hass.data[DOMAIN] is None:
        _LOGGER.error("Unfolded Circle integration not configured")
        connection.send_result(msg["id"])
        return

    coordinator: UCClientInterface = (
        next(iter(hass.data[DOMAIN].values()))
    ).get(UNFOLDED_CIRCLE_COORDINATOR, None)
    if coordinator is None:
        _LOGGER.error("Unfolded Circle coordinator not initialized")
        connection.send_result(msg["id"])
        return

    cancel_callback = connection.subscriptions.get(msg["id"], None)
    if cancel_callback is not None:
        cancel_callback()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/event/subscribed_entities",
    vol.Optional("data"): dict[any, any],
})
@callback
def ws_subscribe_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Subscribe to incoming and outgoing events."""
    if hass.data[DOMAIN] is None:
        _LOGGER.error("Unfolded Circle integration not configured")
        return

    coordinator: UCClientInterface = (
        next(iter(hass.data[DOMAIN].values()))
    ).get(UNFOLDED_CIRCLE_COORDINATOR, None)
    if coordinator is None:
        _LOGGER.error("Unfolded Circle coordinator not initialized")

    coordinator.subscribe_entities_events(connection, msg)
    connection.send_result(msg["id"])
