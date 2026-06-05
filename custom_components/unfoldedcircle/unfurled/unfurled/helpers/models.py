"""Data models, enumerations, and WebSocket event types for Unfurled."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ActivityState(StrEnum):
    """Possible states for an Activity entity."""

    ON = "ON"
    OFF = "OFF"
    RUNNING = "RUNNING"
    UNAVAILABLE = "UNAVAILABLE"


class MediaPlayerState(StrEnum):
    """Playback and availability states for a media player entity."""

    ON = "ON"
    OFF = "OFF"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    STANDBY = "STANDBY"
    BUFFERING = "BUFFERING"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class PowerMode(StrEnum):
    """Remote device power modes."""

    NORMAL = "NORMAL"
    IDLE = "IDLE"
    LOW_POWER = "LOW_POWER"
    SUSPEND = "SUSPEND"


class UpdateType(StrEnum):
    """Indicates what kind of data was last changed by a WebSocket push."""

    ACTIVITY = "ACTIVITY"
    BATTERY = "BATTERY"
    AMBIENT_LIGHT = "AMBIENT_LIGHT"
    CONFIGURATION = "CONFIGURATION"
    MEDIA_PLAYER = "MEDIA_PLAYER"
    SOFTWARE = "SOFTWARE"
    NONE = "NONE"


class RemoteCommand(StrEnum):
    """Commands that can be sent to a Remote via ``POST /system?cmd=…``."""

    STANDBY = "STANDBY"
    REBOOT = "REBOOT"
    POWER_OFF = "POWER_OFF"
    RESTART = "RESTART"
    RESTART_UI = "RESTART_UI"
    RESTART_CORE = "RESTART_CORE"


class DockCommand(StrEnum):
    """Commands that can be sent directly to a Dock."""

    SET_LED_BRIGHTNESS = "SET_LED_BRIGHTNESS"
    IDENTIFY = "IDENTIFY"
    REBOOT = "REBOOT"


# ---------------------------------------------------------------------------
# Settings dataclasses (mirrors GET /cfg response)
# ---------------------------------------------------------------------------


@dataclass
class DisplaySettings:
    """Settings from ``/cfg`` → ``display``."""

    auto_brightness: bool = False
    brightness: int = 50


@dataclass
class ButtonSettings:
    """Settings from ``/cfg`` → ``button``."""

    auto_brightness: bool = False
    brightness: int = 50
    static_color: dict | None = None


@dataclass
class SoundSettings:
    """Settings from ``/cfg`` → ``sound``."""

    enabled: bool = True
    volume: int = 50


@dataclass
class HapticSettings:
    """Settings from ``/cfg`` → ``haptic``."""

    enabled: bool = True


@dataclass
class PowerSavingSettings:
    """Settings from ``/cfg`` → ``power_saving``."""

    display_off_sec: int = 30
    wakeup_sensitivity: int = 2
    standby_sec: int = 900


@dataclass
class WiFiSettings:
    """Settings from ``/cfg`` → ``network`` → ``wifi``."""

    wake_on_wlan: bool = False
    band: str = "auto"
    scan_interval_sec: int = 15
    ipv4_type: str = "DHCP"


@dataclass
class NetworkSettings:
    """Settings from ``/cfg`` → ``network``."""

    bt_enabled: bool = True
    wifi_enabled: bool = True
    wifi: WiFiSettings = field(default_factory=WiFiSettings)
    bt_address: str = ""


@dataclass
class SoftwareUpdateSettings:
    """Settings from ``/cfg`` → ``software_update``."""

    check_for_updates: bool = True
    auto_update: bool = False
    ota_window_start: str = "02:00:00"
    ota_window_end: str = "05:00:00"
    channel: str = "STABLE"


@dataclass
class BluetoothSettings:
    """Settings from ``/cfg`` → ``bt``."""

    peripheral_connections: int = 1
    advertisement_name: str = ""
    enable_hci_log: bool = False
    enable_debug_port: bool = False
    version: str = ""


@dataclass
class ProfileSettings:
    """Settings from ``/cfg`` → ``profile``."""

    has_admin_pin: bool = False


@dataclass
class Feature:
    """A feature-flag entry from ``/cfg`` → ``features``."""

    id: str = ""
    enabled: bool = False
    title: dict = field(default_factory=dict)
    description: dict = field(default_factory=dict)
    help_url: str = ""


@dataclass
class VoiceSettings:
    """Settings from ``/cfg`` → ``voice``."""

    microphone: bool = False
    voice_assistant: dict = field(default_factory=dict)


@dataclass
class LocalizationInfo:
    """Settings from ``/cfg`` → ``localization``."""

    language_code: str = "en_US"
    country_code: str = "US"
    time_zone: str = "UTC"
    time_format_24h: bool = True
    measurement_unit: str = "METRIC"


@dataclass
class RemoteSettings:
    """Aggregated, structured view of all device configuration settings.

    Populated from a single ``GET /cfg`` call.  Individual sections are
    updated via the corresponding ``PATCH /cfg/<section>`` endpoints.
    """

    display: DisplaySettings = field(default_factory=DisplaySettings)
    button: ButtonSettings = field(default_factory=ButtonSettings)
    sound: SoundSettings = field(default_factory=SoundSettings)
    haptic: HapticSettings = field(default_factory=HapticSettings)
    power_saving: PowerSavingSettings = field(default_factory=PowerSavingSettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)
    software_update: SoftwareUpdateSettings = field(default_factory=SoftwareUpdateSettings)
    localization: LocalizationInfo = field(default_factory=LocalizationInfo)
    bluetooth: BluetoothSettings = field(default_factory=BluetoothSettings)
    profile: ProfileSettings = field(default_factory=ProfileSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    features: list[Feature] = field(default_factory=list)


# ---------------------------------------------------------------------------
# System / device info dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DeviceInfo:
    """Combined static and runtime device information.

    Populated during :meth:`~unfurled.remote.Remote.init` from the system-info
    and pub/version endpoints.  Hardware details (model, revision) and runtime
    identity (name, IP, firmware version) live together here.
    """

    # Hardware / factory info (from GET /system)
    _model_name: str = field(default="", repr=False)
    model_number: str = ""
    serial_number: str = ""
    _hw_revision: str = field(default="", repr=False)
    manufacturer: str = "Unfolded Circle"

    # Runtime identity)
    _name: str = field(default="", repr=False)
    hostname: str = ""
    mac_address: str = ""
    ip_address: str = ""
    _sw_version: str = field(default="", repr=False)
    is_simulator: bool | None = None

    @property
    def model_name(self) -> str:
        """Human-readable model name, derived from ``model_number`` if not set by the API."""
        if self._model_name:
            return self._model_name
        num = self.model_number.upper()
        if num == "UCR2":
            return "Remote Two"
        if num == "UCR3":
            return "Remote 3"
        return self._model_name  # empty string fallback

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._model_name = value

    @property
    def hw_revision(self) -> str:
        """Hardware revision in human-readable form (e.g. ``"Revision 2"``)."""
        if self._hw_revision == "rev2":
            return "Revision 2"
        if self._hw_revision == "rev3":
            return "Revision 3"
        return self._hw_revision

    @hw_revision.setter
    def hw_revision(self, value: str) -> None:
        self._hw_revision = value

    @property
    def name(self) -> str:
        """Human-friendly name for the remote, if available; otherwise a generic fallback."""
        return self._name or "Unfolded Circle Remote"

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def sw_version(self) -> str:
        """Software version of the remote, if available."""
        return self._sw_version or "N/A"

    @sw_version.setter
    def sw_version(self, value: str) -> None:
        self._sw_version = value


@dataclass
class RemoteState:
    """Volatile real-time state updated by polling and WebSocket events."""

    battery_level: int = 0
    battery_status: str = ""
    is_charging: bool = False
    ambient_light_level: int = 0
    power_mode: str = PowerMode.NORMAL
    online: bool = True
    is_wireless_charging: bool = False


@dataclass
class RemoteFeatureFlags:
    """Device capability flags detected during ``init()``."""

    external_entity_configuration_available: bool = False
    new_web_configurator: bool = True
    charging_options: list = field(default_factory=list)
    wireless_charging_enabled: bool = False
    button_features: list[str] = field(default_factory=list)


@dataclass
class RemoteStats:
    """System resource statistics from ``GET /pub/status``."""

    _memory_total: float = 0.0
    _memory_available: float = 0.0
    _storage_total: float = 0.0
    _storage_available: float = 0.0
    cpu_load_one: float = 0.0
    cpu_load_five: float = 0.0
    cpu_load_fifteen: float = 0.0

    @property
    def memory_available(self) -> int:
        """Available memory on the remote."""
        return int(round(self._memory_available))

    @property
    def storage_available(self) -> int:
        """Available storage on the remote."""
        return int(round(self._storage_available))

    @memory_available.setter
    def memory_available(self, value: float) -> None:
        self._memory_available = value

    @storage_available.setter
    def storage_available(self, value: float) -> None:
        self._storage_available = value

    @property
    def memory_total(self) -> int:
        """Total RAM in MiB."""
        return int(round(self._memory_total))

    @property
    def storage_total(self) -> int:
        """Total user-data storage in MiB."""
        return int(round(self._storage_total))

    @memory_total.setter
    def memory_total(self, value: float) -> None:
        self._memory_total = value

    @storage_total.setter
    def storage_total(self, value: float) -> None:
        self._storage_total = value


@dataclass
class UpdateInfo:
    """Software update status from ``GET /update``."""

    in_progress: bool = False
    update_percent: int = 0
    download_percent: int = 0
    latest_version: str = ""
    release_notes_url: str = ""
    release_notes: str = ""
    next_check_date: str = ""
    available: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# WebSocket event dataclasses  (parsed from raw WS messages)
# ---------------------------------------------------------------------------


@dataclass
class BatteryEvent:
    """Fired when battery status changes (e.g. level, charging state)."""

    status: str
    capacity: int
    power_supply: bool


@dataclass
class AmbientLightEvent:
    """Fired when the remote's ambient light sensor detects a change in lighting conditions."""

    intensity: int


@dataclass
class ActivityStateEvent:
    """Fired when an activity's running state changes."""

    entity_id: str
    state: str
    included_entities: list[dict] = field(default_factory=list)


@dataclass
class ActivityEntityLinkEvent:
    """Fired when a RUNNING activity step reveals an entity↔activity binding."""

    activity_id: str
    entity_id: str
    entity_data: dict


@dataclass
class MediaPlayerAttributesEvent:
    """Fired when a media player entity's attributes change."""

    entity_id: str
    attributes: dict


@dataclass
class SoftwareUpdateEvent:
    """Fired when a software update starts, progresses, or completes."""

    event_type: str
    progress: dict = field(default_factory=dict)


@dataclass
class ConfigurationChangeEvent:
    """Fired when device configuration is changed remotely."""

    new_state: dict


@dataclass
class PowerModeEvent:
    """Fired when the device transitions between power modes."""

    mode: str


@dataclass
class IRLearningEvent:
    """Fired when the dock finishes learning an IR code."""

    device_id: str
    code: dict


# ---------------------------------------------------------------------------
# WebSocket message parser
# ---------------------------------------------------------------------------


def parse_ws_message(
    raw: str,
) -> (
    BatteryEvent
    | AmbientLightEvent
    | ActivityStateEvent
    | ActivityEntityLinkEvent
    | MediaPlayerAttributesEvent
    | SoftwareUpdateEvent
    | ConfigurationChangeEvent
    | PowerModeEvent
    | IRLearningEvent
    | None
):
    """Parse a raw WebSocket message string into a typed event object.

    Returns ``None`` for messages that are not actionable (e.g. ack frames).
    """
    try:
        data: dict = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _LOGGER.debug("Unfurled: could not parse WS message: %r", raw)
        return None

    msg = data.get("msg")
    msg_data: dict = data.get("msg_data") or {}

    # ---- top-level message types ----
    if msg == "ambient_light":
        return AmbientLightEvent(intensity=msg_data.get("intensity", 0))

    if msg == "battery_status":
        return BatteryEvent(
            status=msg_data.get("status", ""),
            capacity=msg_data.get("capacity", 0),
            power_supply=bool(msg_data.get("power_supply", False)),
        )

    if msg == "ir_learning":
        return IRLearningEvent(
            device_id=msg_data.get("device_id", ""),
            code=msg_data.get("code", {}),
        )

    if msg == "software_update":
        return SoftwareUpdateEvent(
            event_type=msg_data.get("event_type", ""),
            progress=msg_data.get("progress", {}),
        )

    if msg == "configuration_change":
        return ConfigurationChangeEvent(new_state=msg_data.get("new_state", {}))

    if msg == "power_mode_change":
        return PowerModeEvent(mode=msg_data.get("mode", "NORMAL"))

    # ---- entity_change sub-dispatch ----
    if msg == "entity_change":
        return _parse_entity_change(msg_data)

    return None


def _parse_entity_change(
    msg_data: dict,
) -> ActivityStateEvent | ActivityEntityLinkEvent | MediaPlayerAttributesEvent | None:
    entity_type = msg_data.get("entity_type")
    entity_id: str = msg_data.get("entity_id", "")
    new_state: dict = msg_data.get("new_state") or {}
    attributes: dict = new_state.get("attributes") or {}

    if entity_type == "media_player" and attributes:
        return MediaPlayerAttributesEvent(entity_id=entity_id, attributes=attributes)

    if entity_type == "activity":
        state = attributes.get("state", "")

        # Activity is sequencing through its "on" steps - extract entity link
        if state == "RUNNING":
            try:
                step = attributes["step"]
                if (
                    step["entity"]["type"] == "media_player"
                    and step["command"]["cmd_id"] == "media_player.on"
                ):
                    linked_entity_id = step["command"]["entity_id"]
                    entity_data = {**step["entity"], "entity_id": linked_entity_id}
                    return ActivityEntityLinkEvent(
                        activity_id=entity_id,
                        entity_id=linked_entity_id,
                        entity_data=entity_data,
                    )
            except (KeyError, TypeError):
                pass

        if state in ("ON", "OFF"):
            included: list[dict] = []
            options = new_state.get("options") or {}
            if options.get("included_entities"):
                included = options["included_entities"]
            return ActivityStateEvent(entity_id=entity_id, state=state, included_entities=included)

    return None
