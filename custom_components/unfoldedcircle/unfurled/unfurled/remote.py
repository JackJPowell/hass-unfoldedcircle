"""Remote - the primary entry point for interacting with an Unfolded Circle remote."""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

import aiohttp
from packaging.version import Version
from wakeonlan import send_magic_packet

from unfurled.api import CoreAPI
from unfurled.dock import Dock
from unfurled.entities.activity import Activity, ActivityGroup
from unfurled.entities.ir import IR, IRCodeset, IREmitter
from unfurled.entities.media_player import MediaPlayerEntity
from unfurled.helpers.exceptions import (
    AuthenticationError,
    HTTPError,
    InvalidButtonCommand,
    NoActivityRunning,
    RemoteIsSleeping,
)
from unfurled.helpers.helpers import Helpers
from unfurled.helpers.models import (
    ActivityEntityLinkEvent,
    ActivityStateEvent,
    AmbientLightEvent,
    BatteryEvent,
    ConfigurationChangeEvent,
    DeviceInfo,
    IRLearningEvent,
    MediaPlayerAttributesEvent,
    PowerMode,
    PowerModeEvent,
    RemoteState,
    SoftwareUpdateEvent,
    UpdateType,
    parse_ws_message,
)
from unfurled.helpers.websocket import RemoteWebSocketClient
from unfurled.submodules.authentication import Authentication
from unfurled.submodules.integrations import Integrations
from unfurled.submodules.settings import Settings
from unfurled.submodules.systems import System

_LOGGER = logging.getLogger(__name__)

_SIMULATOR_MAC = "aa:bb:cc:dd:ee:ff"
_SIMULATOR_NAMES = {"Remote Two Simulator", "Remote 3 Simulator"}


class Remote:
    """High-level API for an Unfolded Circle remote device.

    Manages REST calls via :class:`~unfurled.api.CoreAPI` and receives
    real-time pushes via a :class:`~unfurled.websocket.RemoteWebSocketClient`.

    Typical usage::

        remote = Remote("http://192.168.1.10/api/", api_key="mykey")
        await remote.init()          # populate all state
        await remote.connect_websocket()  # keep state in sync via WS

        print(remote.battery_level)
        await remote.activities[0].turn_on()

        await remote.close()         # clean up sessions / sockets
    """

    def __init__(
        self,
        api_url: str,
        *,
        pin: str | None = None,
        api_key: str | None = None,
        session: aiohttp.ClientSession | None = None,
        wake_if_asleep: bool = True,
        wake_on_lan_retries: int = 3,
    ) -> None:
        self.endpoint = self._normalize_url(api_url)
        self.configuration_url = self._derive_config_url(self.endpoint)

        self.api = CoreAPI(self.endpoint, api_key=api_key, pin=pin, session=session)

        self._api_key = api_key
        self._pin = pin

        # Device info (hardware details + runtime identity)
        self.device = DeviceInfo()

        # Real-time state (battery, ambient light, power mode, …)
        self.state = RemoteState()

        # Settings  (all sub-sections live here, populated from GET /cfg)
        self.settings = Settings(self)

        # System (feature flags, stats, update info, standby inhibitors)
        self.system = System(self)

        # Helpers
        self.helpers = Helpers(self)

        # Authentication
        self.auth = Authentication(self)

        # Integrations
        self.integrations = Integrations(self)

        # IR control
        self.ir = IR(self)

        # Collections
        self.activities: list[Activity] = []
        self.activity_groups: list[ActivityGroup] = []
        self.docks: list[Dock] = []
        self.ir_emitters: list[IREmitter] = []
        self.ir_codesets: list[IRCodeset] = []

        # Wake-on-LAN
        self._wake_if_asleep = wake_if_asleep
        self._wake_on_lan_retries = wake_on_lan_retries

        # WebSocket
        self._ws_client: RemoteWebSocketClient | None = None
        self._last_update_type: UpdateType = UpdateType.NONE

        # Entities cache (media players referenced by activities)
        self._entities: dict[str, MediaPlayerEntity] = {}

    # ------------------------------------------------------------------
    # URL helpers (static / class)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Ensure the URL has a scheme and ends in ``/api/``."""
        if not re.match(r"^https?://", url):
            url = "http://" + url
        parsed = urlparse(url)
        if parsed.path in ("", "/"):
            url = f"{parsed.scheme}://{parsed.netloc}/api/"
        elif not parsed.path.endswith("/"):
            url = url + "/"
        return url

    @staticmethod
    def _derive_config_url(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}/configurator/"

    # ------------------------------------------------------------------
    # Wake-on-LAN helpers
    # ------------------------------------------------------------------

    async def _ensure_awake(self) -> None:
        """Wake the remote if WoL is configured and it may be asleep."""
        if (
            self._wake_if_asleep
            and self.settings.network.wifi.wake_on_wlan
            and not await self.wake()
        ):
            raise RemoteIsSleeping

    async def wake(self, *, wait: bool = True) -> bool:
        """Send a magic packet and optionally wait for the remote to respond."""
        if self.device.is_simulator:
            return True
        return await Remote.wake_by_mac(
            self.device.mac_address,
            self.endpoint,
            wait_for_confirmation=wait,
            retries=self._wake_on_lan_retries,
        )

    @classmethod
    async def wake_by_mac(
        cls,
        mac_address: str,
        api_url: str,
        *,
        wait_for_confirmation: bool = True,
        retries: int = 3,
    ) -> bool:
        """Send a WoL magic packet and optionally verify the device is awake."""
        validated_url = cls._normalize_url(api_url)
        send_magic_packet(mac_address)
        if not wait_for_confirmation:
            return True

        status_url = urljoin(validated_url, "pub/status")
        for _ in range(retries):
            try:
                async with aiohttp.ClientSession() as s:  # noqa: SIM117
                    async with s.get(status_url, timeout=aiohttp.ClientTimeout(total=2)) as r:
                        if r.status == 200:
                            return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    @classmethod
    async def get_version_information(cls, api_url: str) -> dict:
        """Fetch version information from ``GET /pub/version`` without authentication.

        Suitable for use during mDNS discovery before credentials are known.

        Args:
            api_url: Base API URL (e.g. ``"http://192.168.1.10:8080/api/"``).

        Returns:
            Raw JSON dict from the endpoint, or an empty dict on failure.
        """
        validated_url = cls._normalize_url(api_url)
        version_url = urljoin(validated_url, "pub/version")
        try:
            async with aiohttp.ClientSession() as s:  # noqa: SIM117
                async with s.get(version_url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    r.raise_for_status()
                    return await r.json()
        except Exception:
            return {}

    @staticmethod
    def name_from_model_id(model_id: str) -> str:
        """Return the marketing name for a given mDNS model identifier.

        Args:
            model_id: Model string from the ``model`` mDNS property
                (e.g. ``"UCR2"``, ``"UCR3"``).

        Returns:
            Human-readable device name, or *model_id* unchanged if unknown.
        """
        return {
            "UCR2": "Remote Two",
            "UCR2-simulator": "Remote Two Simulator",
            "UCR3": "Remote 3",
            "UCR3-simulator": "Remote 3 Simulator",
        }.get(model_id, model_id)

    @classmethod
    async def resolve_discovery(
        cls,
        host: str,
        port: int,
        model: str,
    ) -> dict:
        """Resolve device name and MAC address from mDNS discovery properties.

        This classmethod does not require credentials. For real hardware it hits
        ``GET /pub/version`` to obtain the device-assigned name and MAC address.
        Simulator models are resolved locally without a network call.

        Args:
            host: IP address or hostname of the device.
            port: HTTP port of the device.
            model: Value of the ``model`` mDNS property (e.g. ``"UCR2"``).

        Returns:
            Dict with keys ``name``, ``mac_address``, ``endpoint``, and
            ``configuration_url``.
        """
        endpoint = f"http://{host}:{port}/api/"
        configuration_url = f"http://{host}:{port}/configurator/"
        device_name = cls.name_from_model_id(model)
        mac_address = ""

        if "simulator" in model.lower():
            # Simulators share a fixed placeholder MAC and don't need a network call.
            mac_address = "aabbccddeeff"
        else:
            try:
                version = await cls.get_version_information(endpoint)
                device_name = version.get("device_name") or device_name
                mac_address = version.get("address", "").replace(":", "").lower()
            except Exception:
                pass

        return {
            "name": device_name,
            "mac_address": mac_address,
            "endpoint": endpoint,
            "configuration_url": configuration_url,
        }

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def connect_websocket(self, *, reconnect_delay: float = 10.0) -> None:
        """Start a WebSocket connection and keep it alive automatically.

        WebSocket messages update the remote's state in real time.
        """
        if not self._api_key:
            _LOGGER.warning("No API key - WebSocket requires an API key")
            return

        self._ws_client = RemoteWebSocketClient(
            self.endpoint, self._api_key, reconnect_delay=reconnect_delay
        )
        self._ws_client.on_message(self._handle_ws_message)
        self._ws_client.on_connect(self._on_ws_reconnect)
        await self._ws_client.connect()

    async def disconnect_websocket(self) -> None:
        """Close the WebSocket connection."""
        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None

    async def _on_ws_reconnect(self) -> None:
        _LOGGER.debug("Remote WS reconnected - refreshing state")
        await self.update()

    async def _handle_ws_message(self, raw: str) -> None:
        """Dispatch a raw WebSocket message to the appropriate handler."""
        event = parse_ws_message(raw)
        if event is None:
            return

        match event:
            case BatteryEvent():
                self._on_battery(event)
            case AmbientLightEvent():
                self._on_ambient_light(event)
            case ActivityStateEvent():
                self._on_activity_state(event)
            case ActivityEntityLinkEvent():
                self._on_activity_entity_link(event)
            case MediaPlayerAttributesEvent():
                self._on_media_player_attrs(event)
            case SoftwareUpdateEvent():
                self.system._on_software_update(event)
            case ConfigurationChangeEvent():
                self.settings._on_configuration_change(event)
            case PowerModeEvent():
                self._on_power_mode(event)
            case IRLearningEvent():
                self._on_ir_learning(event)

    # WS event handlers (private, synchronous)

    def _on_battery(self, event: BatteryEvent) -> None:
        _LOGGER.debug("WS battery: cap=%s status=%s", event.capacity, event.status)
        self.state.battery_level = event.capacity
        self.state.battery_status = event.status
        self.state.is_charging = event.power_supply
        self._last_update_type = UpdateType.BATTERY

    def _on_ambient_light(self, event: AmbientLightEvent) -> None:
        self.state.ambient_light_level = event.intensity
        self._last_update_type = UpdateType.AMBIENT_LIGHT

    def _on_activity_state(self, event: ActivityStateEvent) -> None:
        _LOGGER.debug("WS activity %s → %s", event.entity_id, event.state)
        for activity in self.activities:
            if activity.id == event.entity_id:
                activity._set_state(event.state)
                if event.included_entities:
                    self._apply_included_entities(activity, event.included_entities)
        for group in self.activity_groups:
            if group.contains(event.entity_id):
                group._recalculate_state()
        self._last_update_type = UpdateType.ACTIVITY

    def _on_activity_entity_link(self, event: ActivityEntityLinkEvent) -> None:
        _LOGGER.debug(
            "WS entity link: activity=%s entity=%s",
            event.activity_id,
            event.entity_id,
        )
        for activity in self.activities:
            if activity.id == event.activity_id:
                self._apply_included_entities(activity, [event.entity_data])
        self._last_update_type = UpdateType.ACTIVITY

    def _on_media_player_attrs(self, event: MediaPlayerAttributesEvent) -> None:
        entity = self._entities.get(event.entity_id)
        if entity:
            entity.update_attributes(event.attributes)
            self._last_update_type = UpdateType.MEDIA_PLAYER

    def _on_power_mode(self, event: PowerModeEvent) -> None:
        self.state.power_mode = event.mode
        self._last_update_type = UpdateType.CONFIGURATION

    def _on_ir_learning(self, event: IRLearningEvent) -> None:
        dock = self.find_dock(event.device_id)
        if dock:
            dock._learned_code = event.code

    # ------------------------------------------------------------------
    # Initialization & updates
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Fetch all device state concurrently.

        This is the primary way to populate a freshly created ``Remote``.
        After calling ``init()``, all properties and collections are set.
        """
        _LOGGER.debug("Remote init starting for %s", self.endpoint)

        # First pass - run independent fetches concurrently
        tasks = [
            self._fetch_version(),
            self._fetch_device_info(),
            self._fetch_wifi_info(),
            self.settings._fetch_configuration(),
            self._fetch_battery(),
            self._fetch_power(),
            self.system._fetch_charger(),
            self._fetch_ambient_light(),
            self.system._fetch_stats(),
            self.system._fetch_update_info(),
            self._fetch_ir_emitters(),
            self._fetch_docks(),
            self._fetch_ir_codesets(),
        ]

        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as exc:
                _LOGGER.debug("Remote init task error: %s", exc)

        # Activities must be loaded before groups
        try:
            await self._fetch_activities()
        except Exception as exc:
            _LOGGER.error("Remote init: failed to fetch activities: %s", exc)

        try:
            await self._fetch_activity_groups()
        except Exception as exc:
            _LOGGER.debug("Remote init: failed to fetch activity groups: %s", exc)

        _LOGGER.debug("Remote init complete for %s", self.endpoint)

    async def update(self) -> None:
        """Refresh volatile state (battery, stats, settings, activity states)."""
        tasks = [
            self._fetch_battery(),
            self._fetch_ambient_light(),
            self.system._fetch_stats(),
            self.settings._fetch_configuration(),
            self.system._fetch_update_info(),
            self.system._fetch_charger(),
            self._fetch_activities_state(),
            self._fetch_power(),
        ]
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as exc:
                _LOGGER.debug("Remote update task error: %s", exc)

    # ------------------------------------------------------------------
    # Internal fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_version(self) -> None:
        data = await self.api.get_pub_version()
        self.device.hostname = data.get("hostname", "")
        self.device.mac_address = data.get("address", "")
        if not self.device.mac_address:
            # Simulator path: get from /system
            await self._fetch_device_info()
        if self.device.is_simulator is not True:
            self.device.sw_version = data.get("os", "")
            v = Version(self.device.sw_version) if self.device.sw_version else None
            if v:
                self.system.flags.external_entity_configuration_available = v >= Version("2.0.0")
                self.system.flags.new_web_configurator = v >= Version("2.2.0")

    async def _fetch_device_info(self) -> None:
        data = await self.api.get_system_info()
        self.device.model_name = data.get("model_name", "")
        self.device.model_number = data.get("model_number", "")
        self.device.serial_number = data.get("serial_number", "")
        self.device.hw_revision = data.get("hw_revision", "")
        if self.device.model_name in _SIMULATOR_NAMES:
            self.device.is_simulator = True
            self.device.mac_address = _SIMULATOR_MAC
            self.system.flags.external_entity_configuration_available = True

    async def _fetch_wifi_info(self) -> None:
        if self.device.is_simulator:
            parsed = urlparse(self.endpoint)
            self.device.ip_address = parsed.hostname or ""
            return
        try:
            data = await self.api.get_wifi_info()
            self.device.mac_address = data.get("address", self.device.mac_address)
            self.device.ip_address = data.get("ip_address", "")
        except Exception:
            pass

    async def _fetch_battery(self) -> None:
        data = await self.api.get_battery()
        self.state.battery_level = data.get("capacity", 0)
        self.state.battery_status = data.get("status", "")
        self.state.is_charging = bool(data.get("power_supply", False))

    async def _fetch_power(self) -> None:
        data = await self.api.get_power()
        self.state.power_mode = data.get("mode", PowerMode.NORMAL)

    async def _fetch_ambient_light(self) -> None:
        data = await self.api.get_ambient_light()
        self.state.ambient_light_level = data.get("intensity", 0)

    async def _fetch_activities(self) -> None:
        """Fetch activities and their button mappings."""
        self.activities = []
        raw = await self.api.get_activities()
        for item in raw:
            activity = Activity(item, self)
            self.activities.append(activity)

            # Fetch detailed activity data (included entities)
            try:
                detail = await self.api.get_activity(activity.id)
                included = detail.get("options", {}).get("included_entities", [])
                self._apply_included_entities(activity, included)
            except Exception:
                pass

            # Fetch button mappings
            try:
                buttons = await self.api.get_activity_buttons(activity.id)
                for btn in buttons:
                    activity._apply_button_mapping(btn.get("button", ""), btn.get("short_press"))
            except Exception:
                pass

    async def _fetch_activities_state(self) -> None:
        """Lightweight refresh of activity on/off states."""
        try:
            raw = await self.api.get_activities()
            for item in raw:
                for activity in self.activities:
                    if activity.id == item["entity_id"]:
                        activity._set_state(item["attributes"]["state"])
        except Exception as exc:
            _LOGGER.debug("_fetch_activities_state error: %s", exc)

    async def _fetch_activity_groups(self) -> None:
        self.activity_groups = []
        raw = await self.api.get_activity_groups()
        for item in raw:
            group = ActivityGroup(
                group_id=item["group_id"],
                name=self.settings.get_text_for_locale(
                    item.get("name", {}), default_text="Unnamed Group"
                ),
                remote=self,
                state=item.get("state", "OFF"),
            )
            try:
                detail = await self.api.get_activity_group(item["group_id"])
                for act_ref in detail.get("activities", []):
                    for activity in self.activities:
                        if activity.id == act_ref.get("entity_id"):
                            group.activities.append(activity)
            except Exception:
                pass
            self.activity_groups.append(group)

    async def _fetch_docks(self) -> None:
        self.docks = []
        raw = await self.api.get_docks()
        for item in raw:
            dock = Dock.from_dict(
                item,
                api_key=self._api_key or "",
                remote_endpoint=self.endpoint,
                remote_configuration_url=self.configuration_url,
            )
            self.docks.append(dock)

    async def _fetch_ir_emitters(self) -> None:
        self.ir_emitters = []
        raw = await self.api.get_ir_emitters()
        for item in raw:
            self.ir_emitters.append(IREmitter(item, self))

    async def _fetch_ir_codesets(self) -> None:
        """Fetch codesets for all registered IR remotes."""
        self.ir_codesets = []
        try:
            remotes = await self.api.get_remotes()
            for remote in remotes:
                try:
                    raw = await self.api.get_remote_ir_codesets(remote.get("entity_id", ""))
                    self.ir_codesets.extend(IRCodeset.from_dict(c) for c in raw)
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def _get_media_player(self, entity_id: str) -> MediaPlayerEntity:
        """Return the cached :class:`~unfurled.media_player.MediaPlayerEntity` or create one."""
        if entity_id not in self._entities:
            self._entities[entity_id] = MediaPlayerEntity(entity_id, self)
        return self._entities[entity_id]

    def _apply_included_entities(self, activity: Activity, included_entities: list[dict]) -> None:
        """Register media player entities from an activity's included entity list."""
        activity._included_entities = included_entities
        for entity_info in included_entities:
            if entity_info.get("entity_type") != "media_player":
                continue
            eid = entity_info.get("entity_id", "")
            if not eid:
                continue
            entity = self._get_media_player(eid)
            entity._name = self.settings.get_text_for_locale(
                entity_info.get("name", {}), default_text=eid
            )
            entity._entity_commands = entity_info.get("entity_commands", [])
            entity._activity = activity
            activity.add_media_player_entity(entity)

    def find_activity(self, activity_id: str) -> Activity | None:
        """Return the activity with the given ID, or ``None`` if not found."""
        return next((a for a in self.activities if a.id == activity_id), None)

    def find_dock(self, dock_id: str) -> Dock | None:
        """Return the dock with the given ID, or ``None`` if not found."""
        return next((d for d in self.docks if d.device.id == dock_id), None)

    def get_all_entities_in_use(self, integration_id_filter: str = "") -> list[str]:
        """Return entity IDs referenced by any loaded activity.

        Reads from the already-loaded activity list; does not make an API call.

        Args:
            integration_id_filter: If non-empty, only return IDs that start
                with this string (e.g. ``"hass."`` to scope to one integration).
        """
        entity_ids: list[str] = []
        for activity in self.activities:
            for entity in activity.included_entities:
                eid = entity.get("entity_id", "")
                if integration_id_filter and not eid.startswith(integration_id_filter):
                    continue
                if eid and eid not in entity_ids:
                    entity_ids.append(eid)
        return entity_ids

    # ------------------------------------------------------------------
    # Activity operations
    # ------------------------------------------------------------------

    async def get_active_activities(self) -> list[Activity]:
        """Return all currently active (ON) activities."""
        await self._fetch_activities_state()
        return [a for a in self.activities if a.is_on]

    async def send_button_command(
        self,
        button: str,
        *,
        activity: str | None = None,
        hold: bool = False,
        repeat: int = 1,
    ) -> None:
        """Send a predefined physical button command.

        Args:
            button: Button identifier (e.g. ``"VOLUME_UP"``).
            activity: Optional activity name to scope the command to.
            hold: Use the long-press mapping instead of short-press.
            repeat: Number of times to send the command.
        """
        await self._ensure_awake()

        activity_id: str | None = None
        if activity:
            act_obj = next((a for a in self.activities if a.name == activity), None)
            if act_obj:
                activity_id = act_obj.id
        else:
            active = [a for a in self.activities if a.is_on]
            if active:
                activity_id = active[0].id

        if not activity_id:
            raise NoActivityRunning

        try:
            btn_data = await self.api.get_activity_button(activity_id, button.upper())
        except HTTPError as exc:
            raise InvalidButtonCommand(str(exc)) from exc

        action = btn_data.get("long_press" if hold else "short_press", {})
        entity_id = action.get("entity_id", "")
        cmd_id = action.get("cmd_id", "")
        params = action.get("params")

        for _ in range(repeat):
            await self.api.put_entity_command(entity_id, cmd_id, params)

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def validate_connection(self) -> bool:
        """Check that the remote is reachable and credentials are valid.

        Returns:
            ``True`` if a HEAD request to ``/activities`` returns 200.

        Raises:
            :class:`~unfurled.exceptions.AuthenticationError`: on 401.
            :class:`~unfurled.exceptions.HTTPError`: on other non-200 responses.
        """
        session = await self.api._ensure_session()
        url = self.api._url("activities")
        async with session.head(url) as response:
            if response.status == 401:
                raise AuthenticationError("Invalid API key or PIN")
            return response.status == 200

    # ------------------------------------------------------------------
    # Lightweight polling refresh
    # ------------------------------------------------------------------

    async def polling_update(self) -> None:
        """Fetch only lightweight stats suitable for frequent polling.

        Refreshes CPU load, memory, and storage without touching settings
        or activity state (use :meth:`update` for a full refresh).
        """
        try:
            await self.system._fetch_stats()
        except Exception as exc:
            _LOGGER.debug("polling_update error: %s", exc)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release all resources: WebSocket, HTTP session, dock sessions."""
        await self.disconnect_websocket()
        await self.api.close()
        for dock in self.docks:
            await dock.close()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Remote:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
