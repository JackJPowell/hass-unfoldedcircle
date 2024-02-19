from enum import Enum

AUTH_APIKEY_NAME = "HApyUnfoldedCircle"
AUTH_USERNAME = "web-configurator"
WS_RECONNECTION_DELAY = 30  # seconds


class RemoteUpdateType(Enum):
    ACTIVITY = 0
    BATTERY = 1
    AMBIENT_LIGHT = 2
    OTHER = 10,
    NONE = 99
