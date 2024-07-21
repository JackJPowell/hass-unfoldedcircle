"""Constants for the Unfolded Circle Remote integration."""

from datetime import timedelta

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
HA_SUPPORTED_DOMAINS = [
    "button",
    "switch",
    "climate",
    "cover",
    "light",
    "media_player",
    "remote",
]
