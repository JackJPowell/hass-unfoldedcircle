"""Constants for Unfolded Circle Library"""

from enum import Enum

AUTH_APIKEY_NAME = "pyUnfoldedCircle"
AUTH_USERNAME = "web-configurator"
WS_RECONNECTION_DELAY = 30  # seconds
ZEROCONF_TIMEOUT = 3
ZEROCONF_SERVICE_TYPE = "_uc-remote._tcp.local."
SIMULATOR_MAC_ADDRESS = "aa:bb:cc:dd:ee:ff"

SYSTEM_COMMANDS = [
    "STANDBY",
    "REBOOT",
    "POWER_OFF",
    "RESTART",
    "RESTART_UI",
    "RESTART_CORE",
]


class RemoteUpdateType(Enum):
    """WS connection update type"""

    ACTIVITY = 0
    BATTERY = 1
    AMBIENT_LIGHT = 2
    CONFIGURATION = 3
    MEDIA_PLAYER = 4
    SOFTWARE = 5
    OTHER = 10
    NONE = 99


class RemotePowerModes(Enum):
    """Remote Power States"""

    NORMAL = "NORMAL"
    IDLE = "IDLE"
    LOW_POWER = "LOW_POWER"
    SUSPEND = "SUSPEND"
