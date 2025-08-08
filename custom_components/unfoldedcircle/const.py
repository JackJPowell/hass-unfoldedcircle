"""Constants for the Unfolded Circle Remote integration."""

from datetime import timedelta

DOMAIN = "unfoldedcircle"
DEFAULT_HASS_URL = "http://homeassistant.local:8123"
CONF_SERIAL = "serial"
CONF_ACTIVITY_GROUP_MEDIA_ENTITIES = "activity_group_media_entities"
CONF_GLOBAL_MEDIA_ENTITY = "global_media_entity"
CONF_ACTIVITY_MEDIA_ENTITIES = "activity_media_entities"
CONF_ACTIVITIES_AS_SWITCHES = "activities_as_switches"
CONF_SUPPRESS_ACTIVITIY_GROUPS = "suppress_activity_groups"
CONF_HA_WEBSOCKET_URL = "ha_ws_url"
CONF_DOCK_ID = "dock_id"
DEVICE_SCAN_INTERVAL = timedelta(seconds=30)
UNFOLDED_CIRCLE_COORDINATOR = "unfolded_circle_coordinator"
UNFOLDED_CIRCLE_DOCK_COORDINATORS = "unfolded_circle_dock_coordinators"
UNFOLDED_CIRCLE_DOCK_COORDINATOR = "unfolded_circle_dock_coordinator"
UNFOLDED_CIRCLE_API = "unfolded_circle_api"
UPDATE_ACTIVITY_SERVICE = "update_activity"
LEARN_IR_COMMAND_SERVICE = "learn_ir_command"
SEND_IR_COMMAND_SERVICE = "send_ir_command"
SEND_BUTTON_COMMAND_SERVICE = "send_button_command"
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
]
UC_HA_TOKEN_ID = "ws-ha-api"
UC_HA_SYSTEM = "hass"
UC_HA_DRIVER_ID = "hass"
