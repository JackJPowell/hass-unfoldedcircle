import logging

from .const import DOMAIN, UCClientInterface, UNFOLDED_CIRCLE_COORDINATOR
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

"""This file implements the necessary methods called through HA websocket for the UC HA integration."""


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "uc/info"
    }
)
@callback
def ws_get_info(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
) -> None:
    """Handle get info command."""

    _LOGGER.debug("Unfolded Circle connect request %s", msg)
    connection.send_message({
        "id": msg["id"],
        "type": "result",
        "success": True,
        "result": {
            "state": "CONNECTED",
            "cat": "DEVICE",
            "version": "1.0.0"
        }
    })


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "uc/event/unsubscribe",
    }
)
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

    coordinator: UCClientInterface = ((next(iter(hass.data[DOMAIN].values())))
                                      .get(UNFOLDED_CIRCLE_COORDINATOR, None))
    if coordinator is None:
        _LOGGER.error("Unfolded Circle coordinator not initialized")
        connection.send_result(msg["id"])
        return

    cancel_callback = connection.subscriptions.get(msg["id"], None)
    if cancel_callback is not None:
        cancel_callback()
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "uc/event/subscribed_entities",
        vol.Optional("data"): dict[any, any]
    }
)
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

    coordinator: UCClientInterface = ((next(iter(hass.data[DOMAIN].values())))
                                      .get(UNFOLDED_CIRCLE_COORDINATOR, None))
    if coordinator is None:
        _LOGGER.error("Unfolded Circle coordinator not initialized")

    coordinator.subscribe_entities_events(connection, msg)
    connection.send_result(msg["id"])
