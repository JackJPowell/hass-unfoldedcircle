"""Constants for the Unfolded Circle Remote integration."""

from datetime import timedelta

from homeassistant.components import websocket_api

DOMAIN = "unfoldedcircle"

CONF_SERIAL = "serial"
CONF_ACTIVITY_GROUP_MEDIA_ENTITIES = "activity_group_media_entities"
CONF_GLOBAL_MEDIA_ENTITY = "global_media_entity"
CONF_ACTIVITY_MEDIA_ENTITIES = "activity_media_entities"
CONF_ACTIVITIES_AS_SWITCHES = "activities_as_switches"
CONF_SUPPRESS_ACTIVITIY_GROUPS = "suppress_activity_groups"
DEVICE_SCAN_INTERVAL = timedelta(seconds=30)
UNFOLDED_CIRCLE_COORDINATOR = "unfolded_circle_coordinator"
UNFOLDED_CIRCLE_API = "unfolded_circle_api"
UPDATE_ACTIVITY_SERVICE = "update_activity"


class UCClientInterface:
    """Unfolded Circle interface to handle remote requests"""
    def subscribe_entities_events(self, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        """Method called by the HA websocket component when a remote requests to subscribe to entity events."""
        pass
