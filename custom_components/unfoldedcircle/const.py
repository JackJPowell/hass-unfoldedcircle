"""Constants for the Unfolded Circle Remote integration."""

from datetime import timedelta

DOMAIN = "unfoldedcircle"

CONF_SERIAL = "serial"
CONF_ACTIVITY_GROUP_MEDIA_ENTITIES = "activity_group_media_entities"
CONF_GLOBAL_MEDIA_ENTITY = "global_media_entity"
DEVICE_SCAN_INTERVAL = timedelta(seconds=30)
UNFOLDED_CIRCLE_COORDINATOR = "unfolded_circle_coordinator"
UNFOLDED_CIRCLE_API = "unfolded_circle_api"
