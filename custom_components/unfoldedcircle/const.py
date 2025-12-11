"""Constants for the Unfolded Circle Remote integration."""

from datetime import timedelta

DOMAIN = "unfoldedcircle"
CONF_ACTIVITY_GROUP_MEDIA_ENTITIES = "activity_group_media_entities"
CONF_ACTIVITY_MEDIA_ENTITIES = "activity_media_entities"
CONF_ACTIVITIES_AS_SWITCHES = "activities_as_switches"
CONF_GLOBAL_MEDIA_ENTITY = "global_media_entity"
CONF_SUPPRESS_ACTIVITIY_GROUPS = "suppress_activity_groups"
DEVICE_SCAN_INTERVAL = timedelta(seconds=30)
REMOTE_ON_BEHAVIOR = "remote_on_behavior"
UC_HA_TOKEN_ID = "ws-ha-api"
UC_HA_SYSTEM = "hass"
UC_HA_DRIVER_ID = "hass"
HA_SUPPORTED_DOMAINS = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "input_boolean",
    "input_button",
    "light",
    "media_player",
    "remote",
    "script",
    "scene",
    "sensor",
    "switch",
    "conversation"
]
COMMAND_LIST = [
    "BACK",
    "HOME",
    "VOICE",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "GREEN",
    "DPAD_UP",
    "YELLOW",
    "DPAD_LEFT",
    "DPAD_MIDDLE",
    "DPAD_RIGHT",
    "RED",
    "DPAD_DOWN",
    "BLUE",
    "CHANNEL_UP",
    "CHANNEL_DOWN",
    "MUTE",
    "PREV",
    "PLAY",
    "PAUSE",
    "NEXT",
    "POWER",
]
