"""Custom websocket commands --
Implements the necessary methods called through HA websocket for the UC HA integration."""

import logging
from dataclasses import dataclass
from typing import Any, Callable

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from .helpers import update_config_entities
from .const import DOMAIN, UC_HA_DRIVER_ID

_LOGGER = logging.getLogger(__name__)

INFO_SCHEMA = {
    vol.Required("type"): f"{DOMAIN}/info",
    vol.Optional("message", description="Any String"): str,
    vol.Optional("data", description="Any Dict"): dict[any, any],
}

STATES_SCHEMA = {
    vol.Required("type"): f"{DOMAIN}/entities/states",
    vol.Optional("message", description="Any String"): str,
    vol.Optional("data", description="Any Dict"): dict[any, any],
}


@dataclass
class SubscriptionEvent:
    """Subcription Event Data Class"""

    client_id: str
    driver_id: str
    version: str
    subscription_id: int
    cancel_subscription_callback: Callable
    notification_callback: Callable[[dict[any, any]], None]
    entity_ids: list[str]


@websocket_api.websocket_command(INFO_SCHEMA)
@callback
def ws_get_info(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get info command."""
    _LOGGER.debug(f"Unfolded Circle connect request {DOMAIN}/info %s", msg)
    data = msg.get("data") or {}
    data["version"] = "1.1"

    connection.send_message(
        {
            "id": msg.get("id"),
            "type": "result",
            "success": True,
            "result": {"state": "CONNECTED", "cat": "DEVICE", "version": "1.0.0"},
            "message": msg.get("message"),
            "data": data,
        }
    )


@websocket_api.websocket_command(STATES_SCHEMA)
@callback
def ws_get_states(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get info command."""
    _LOGGER.debug("Unfolded Circle get entities states request from remote %s", msg)
    entity_ids: list[str] = msg.get("data", {}).get("entity_ids", [])
    client_id: str | None = msg.get("data", {}).get("client_id", None)
    entity_states = []
    # If entity_ids list is empty, send all entities
    if len(entity_ids) == 0:
        entity_states = hass.states.async_all()
    else:
        # Check if the registry needs to be updated (available entities unsync)
        if client_id:
            update_config_entities(hass, client_id, entity_ids)
        else:
            _LOGGER.debug(
                "No client ID in the request from remote, cannot update the available entities in HA"
            )

        # Add to the requested list the stored list of entities
        available_entities = []

        # Add the missing available entities (normally the unsubscribed entities) to the get states command
        for entity_id in available_entities:
            if entity_id not in entity_ids:
                entity_ids.append(entity_id)
        _LOGGER.debug("Unfolded circle get states for entities %s", entity_ids)
        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if state is not None:
                entity_states.append(state)
    # Send requested entity states back to remote
    connection.send_message(
        {
            "id": msg.get("id"),
            "type": "result",
            "success": True,
            "result": entity_states,
        }
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/configure/subscribe",
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
    websocket_client.configure_entities_events(connection, msg)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/configure/unsubscribe",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_configure_unsubscribe_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Subscribe event to push modifications of configuration to the remote."""
    subscription_id = msg.get("data", {}).get("subscription_id", "")
    cancel_callback = connection.subscriptions.get(subscription_id, None)
    if cancel_callback is not None:
        _LOGGER.debug(
            f"Unsubscribe {DOMAIN}/event/configure/unsubscribe for id %s",
            subscription_id,
        )
        cancel_callback()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/entities/unsubscribe",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_unsubscribe_entities_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Unsubscribe events."""
    subscription_id = msg.get("data", {}).get("subscription_id", "")
    cancel_callback = connection.subscriptions.get(subscription_id, None)
    if cancel_callback is not None:
        _LOGGER.debug(
            f"Unsubscribe {DOMAIN}/event/entities/unsubscribe for id %s",
            subscription_id,
        )
        cancel_callback()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/event/entities/subscribe",
        vol.Optional("data"): dict[any, any],
    }
)
@callback
def ws_subscribe_entities_event(
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
        websocket_api.async_register_command(hass, ws_get_states)
        websocket_api.async_register_command(hass, ws_subscribe_entities_event)
        websocket_api.async_register_command(hass, ws_unsubscribe_entities_event)
        websocket_api.async_register_command(hass, ws_configure_event)
        websocket_api.async_register_command(hass, ws_configure_unsubscribe_event)
        _LOGGER.debug(
            "Unfolded Circle websocket APIs registered. Ready to receive remotes requests"
        )

    async def close(self):
        _LOGGER.debug("Unfolded Circle close all subscriptions")
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

    def get_subscribed_entities(self, client_id: str) -> SubscriptionEvent | None:
        """Return subscribed entities of given client id (remote's host)"""
        _LOGGER.debug(
            "get_subscribed_entities for client %s : %s", client_id, self._subscriptions
        )
        if client_id is None:
            return None

        found_subscriptions: list[SubscriptionEvent] = []

        for subscription in self._subscriptions:
            _LOGGER.debug(
                "Get subscribed entities for client %s : found client %s, (driver %s)",
                client_id,
                subscription.client_id,
                subscription.driver_id,
            )
            if subscription.client_id == client_id:
                found_subscriptions.append(subscription)

        # There may be several subscriptions for the same client id, take the one with entity IDs
        if len(found_subscriptions) > 0:
            _LOGGER.debug(
                "Found several subscriptions for the same client ID, take the one with subscribed entities"
            )
            for subscription in found_subscriptions:
                if len(subscription.entity_ids) > 0:
                    return subscription
            return found_subscriptions[0]
        return None

    def get_driver_subscription(self, client_id: str) -> SubscriptionEvent | None:
        """Return subscribed entities of given client id (remote's host)"""
        _LOGGER.debug(
            "get_driver_subscription for client %s : %s",
            client_id,
            self._configurations,
        )
        if client_id is None:
            return None
        for subscription in self._configurations:
            if subscription.client_id == client_id:
                _LOGGER.debug(
                    "get_driver_subscription found subscription %s", subscription
                )
                return subscription
        return None

    async def send_configuration_to_remote(
        self, client_id: str, new_configuration: any
    ) -> bool:
        if client_id is None:
            return False
        configuration = self.get_driver_subscription(client_id)
        if configuration is None:
            _LOGGER.warning(
                "Unfolded Circle cannot notify remote %s for new configuration, it is not registered (%s)",
                client_id,
                new_configuration,
            )
            return False
        _LOGGER.debug(
            "Notify new configuration to remote %s (%s)", client_id, new_configuration
        )
        try:
            configuration.notification_callback({"data": new_configuration})
        except Exception as ex:
            _LOGGER.error(
                "Failed to send the new configuration to the remote %s : %s : %s",
                configuration.client_id,
                new_configuration,
                ex,
            )
            return False
        return True

    def subscribe_entities_events(
        self, connection: websocket_api.ActiveConnection, msg: dict
    ):
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
            try:
                subscription.notification_callback(
                    {
                        "data": {
                            "entity_id": entity_id,
                            "new_state": new_state,
                            "old_state": old_state,  # TODO : old state useful ?
                        }
                    }
                )
            except Exception as ex:
                _LOGGER.error(
                    "Failed to notify the remote %s : %s : %s",
                    subscription.client_id,
                    event,
                    ex,
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
        driver_id = data.get("driver_id", UC_HA_DRIVER_ID)
        version = data.get("version", "")

        cancel_callback = async_track_state_change_event(
            self.hass, entities, entities_state_change_event
        )
        subscription = SubscriptionEvent(
            client_id=client_id,
            driver_id=driver_id,
            version=version,
            cancel_subscription_callback=cancel_callback,
            subscription_id=subscription_id,
            notification_callback=forward_event,
            entity_ids=entities,
        )
        self._subscriptions.append(subscription)
        _LOGGER.debug(
            "UC added subscription from remote %s for entity ids %s",
            client_id,
            entities,
        )

        connection.subscriptions[subscription_id] = remove_listener
        # Check if the registry needs to be updated (available entities unsync)
        if client_id:
            update_config_entities(self.hass, client_id, entities)

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
                _LOGGER.debug("UC removed configuration event for remote %s", client_id)
                cancel_callback()
            except Exception:
                pass
            self._configurations.remove(configuration)

        # Create the new events subscription
        subscription_id = msg["id"]
        data = msg["data"]
        client_id = data.get("client_id", "")
        driver_id = data.get("driver_id", UC_HA_DRIVER_ID)
        version = data.get("version", "")

        configuration = SubscriptionEvent(
            client_id=client_id,
            driver_id=driver_id,
            version=version,
            cancel_subscription_callback=cancel_callback,
            subscription_id=subscription_id,
            notification_callback=forward_event,
            entity_ids=[],
        )
        self._configurations.append(configuration)
        _LOGGER.debug("UC added configuration event for remote %s", client_id)

        connection.subscriptions[subscription_id] = remove_listener

        return remove_listener
