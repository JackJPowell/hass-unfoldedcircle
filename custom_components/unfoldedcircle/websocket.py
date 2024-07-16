"""Custom websocket commands --
    Implements the necessary methods called through HA websocket for the UC HA integration."""

import logging
from dataclasses import dataclass
from typing import Callable, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR

_LOGGER = logging.getLogger(__name__)

INFO_SCHEMA = {
    vol.Required("type"): f"{DOMAIN}/info",
    vol.Optional("message", description="Any String"): str,
    vol.Optional("data", description="Any Dict"): dict[any, any],
}


@dataclass
class SubscriptionEvent:
    """Subcription Event Data Class"""

    client_id: str
    subscription_id: int
    cancel_subscription_callback: Callable
    notification_callback: Callable[[dict[any, any]], None]
    entity_ids: list[str] | None


@websocket_api.websocket_command(INFO_SCHEMA)
@callback
def ws_get_info(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
) -> None:
    """Handle get info command."""
    # websocket_client = UCWebsocketClient(hass)
    _LOGGER.debug("Unfolded Circle connect request %s", msg)
    connection.send_message(
        {
            "id": msg.get("id"),
            "type": "result",
            "success": True,
            "result": {"state": "CONNECTED", "cat": "DEVICE", "version": "1.0.0"},
            "message": msg.get("message"),
            "data": msg.get("data"),
        }
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/configure",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_configure_event(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
) -> None:
    """Subscribe event to push modifications of configuration to the remote."""
    websocket_client = UCWebsocketClient(hass)
    websocket_client.subscribe_entities_events(connection, msg)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/unsubscribe",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_unsubscribe_event(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
) -> None:
    """Unsubscribe events."""
    # websocket_client = UCWebsocketClient(hass)
    cancel_callback = connection.subscriptions.get(msg["id"], None)
    if cancel_callback is not None:
        cancel_callback()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/subscribed_entities",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_subscribe_event(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
) -> None:
    """Subscribe to incoming and outgoing events."""
    websocket_client = UCWebsocketClient(hass)
    websocket_client.subscribe_entities_events(connection, msg)
    connection.send_result(msg["id"])


class Singleton(type):
    """Singleton type to instantiate a single instance"""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class UCWebsocketClient(metaclass=Singleton):
    """Websocket client for remote HA integration

    This class will handle commands received by the remote and events to send to notify the remote
    of entities states changed
    """

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        # List of events to subscribe to the websocket
        self._subscriptions: list[SubscriptionEvent] = []
        self._configurations: list[SubscriptionEvent] = []
        websocket_api.async_register_command(hass, ws_get_info)
        websocket_api.async_register_command(hass, ws_subscribe_event)
        websocket_api.async_register_command(hass, ws_unsubscribe_event)
        _LOGGER.debug("Unfolded Circle websocket APIs registered. Ready to receive remotes requests")

    async def close(self):
        for subscription in self._subscriptions:
            try:
                _LOGGER.debug(
                    "Unfolded Circle unregister event %s for remote %s",
                    subscription.subscription_id,
                    subscription.client_id,
                )
                subscription.cancel_subscription_callback()
            except Exception:
                pass
        self._subscriptions = []

    async def get_subscribed_entities(self, client_id: str) -> list[str] | None:
        """Return subscribed entities of given client id (remote's host)"""
        if client_id is None:
            return None
        # TODO better handling of client ids
        client_id = client_id.split(":")[0]
        for subscription in self._subscriptions:
            if subscription.client_id.startswith(client_id):
                return subscription.entity_ids
        return None

    async def send_configuration_to_remote(self, client_id: str, new_configuration: any) -> bool:
        if client_id is None:
            return False
        # TODO better handling of client ids
        client_id = client_id.split(":")[0]
        configuration = None
        for _configuration in self._configurations:
            _LOGGER.debug("send_configuration_to_remote : %s", _configuration.client_id)
            if _configuration.client_id.startswith(client_id):
                configuration = _configuration
                break

        if configuration is None:
            _LOGGER.warning(
                "Unfolded Circle cannot notify remote %s for new configuration, it is not registered (%s)",
                client_id,
                new_configuration
            )
            return False
        _LOGGER.debug("Notify new configuration to remote %s (%s)", client_id, new_configuration)
        configuration.notification_callback({
            "data": new_configuration
        })
        return True

    def subscribe_entities_events(self, connection: websocket_api.ActiveConnection, msg: dict):
        """Adds and handles subscribed event"""
        subscription: SubscriptionEvent | None = None
        cancel_callback: Callable[[], None] | None = None

        @callback
        def forward_event(data: dict[any, any]) -> None:
            """Forward message to websocket subscription."""
            connection.send_event(
                msg["id"],
                data,
            )

        def entities_state_change_event(event: Event[EventStateChangedData]) -> Any:
            """Method called by HA when one of the subscribed entities have changed state."""
            # Note that this method has to be encapsulated in the subscribe_entities_events method
            # in order to maintain a reference to the subscription variable
            entity_id = event.data["entity_id"]
            old_state = event.data["old_state"]
            new_state = event.data["new_state"]
            _LOGGER.debug("Received notification to send to UC remote %s", event)
            subscription.notification_callback(
                {
                    "data": {
                        "entity_id": entity_id,
                        "new_state": new_state,
                        "old_state": old_state,  # TODO : old state useful ?
                    }
                }
            )

        def remove_listener() -> None:
            """Remove the listener."""
            try:
                _LOGGER.debug(
                    "Unfolded Circle unregister subscribe_entities_events %s for remote %s",
                    subscription_id,
                    client_id,
                )
                cancel_callback()
            except Exception:
                pass
            self._subscriptions.remove(subscription)

        # Create the new events subscription
        subscription_id = msg["id"]
        data = msg["data"]
        entities = data.get("entities", [])
        client_id = data.get("client_id", "")

        cancel_callback = async_track_state_change_event(
            self.hass, entities, entities_state_change_event
        )
        subscription = SubscriptionEvent(
            client_id=client_id,
            cancel_subscription_callback=cancel_callback,
            subscription_id=subscription_id,
            notification_callback=forward_event,
            entity_ids=entities,
        )
        self._subscriptions.append(subscription)
        _LOGGER.debug("UC added subscription from remote %s for entity ids %s", client_id, entities)

        connection.subscriptions[subscription_id] = remove_listener

        return remove_listener

    def configure_entities_events(
            self, connection: websocket_api.ActiveConnection, msg: dict
    ):
        """Subscribed event from remotes to receive new configuration data (entities to subscribe)"""
        configuration: SubscriptionEvent | None = None
        cancel_callback: Callable[[], None] | None = None

        @callback
        def forward_event(data: dict[any, any]) -> None:
            """Forward message to websocket subscription."""
            connection.send_event(
                msg["id"],
                data,
            )

        def remove_listener() -> None:
            """Remove the listener."""
            try:
                _LOGGER.debug(
                    "Unfolded Circle unregister configure_entities_events %s for remote %s",
                    subscription_id,
                    client_id,
                )
                cancel_callback()
            except Exception:
                pass
            self._configurations.remove(configuration)

        # Create the new events subscription
        subscription_id = msg["id"]
        data = msg["data"]
        client_id = data.get("client_id", "")

        configuration = SubscriptionEvent(
            client_id=client_id,
            cancel_subscription_callback=cancel_callback,
            subscription_id=subscription_id,
            notification_callback=forward_event,
        )
        self._subscriptions.append(configuration)
        _LOGGER.debug("UC added configuration event from remote %s", client_id)

        connection.subscriptions[subscription_id] = remove_listener

        return remove_listener
