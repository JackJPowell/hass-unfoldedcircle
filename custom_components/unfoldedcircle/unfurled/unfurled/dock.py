"""Dock domain class."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .api import CoreAPI
from .helpers.exceptions import HTTPError
from .helpers.models import DockCommand, UpdateInfo
from .helpers.websocket import DockWebSocketClient

if TYPE_CHECKING:
    from .helpers.websocket import MessageCallback

_LOGGER = logging.getLogger(__name__)

_SIMULATOR_NAMES = {"Remote Two Simulator", "Remote 3 Simulator"}


class Dock:
    """Represents an Unfolded Circle dock device.

    A ``Dock`` can be constructed directly (e.g. from ``Remote.docks``)
    or discovered independently.  It uses the remote's REST API for
    most operations and its own WebSocket for real-time events.
    """

    def __init__(
        self,
        *,
        dock_id: str,
        api_key: str,
        remote_endpoint: str,
        remote_configuration_url: str = "",
        name: str = "",
        ws_url: str = "",
        is_active: bool = False,
        model_number: str = "",
        hardware_revision: str = "",
        serial_number: str = "",
        led_brightness: int = 0,
        ethernet_led_brightness: int = 0,
        software_version: str = "",
        state: str = "",
        is_learning_active: bool = False,
    ) -> None:
        self.configuration_url = remote_configuration_url
        self.api = CoreAPI(remote_endpoint, api_key=api_key)
        self._ws_url = ws_url

        # Device Info
        self.device = DeviceInfo(
            id=dock_id,
            _name=name,
            model_number=model_number,
            hardware_revision=hardware_revision,
            serial_number=serial_number,
            software_version=software_version,
        )

        # State
        self.state = DockState(
            is_active=is_active,
            state=state,
            led_brightness=led_brightness,
            ethernet_led_brightness=ethernet_led_brightness,
            is_learning_active=is_learning_active,
        )

        # Update state
        self.system = System(self)
        self.settings = Settings()

        self._learned_code: dict = {}

        # Auth / connection
        self._api_key = api_key

        # Native WebSocket (direct to dock)
        self._ws_client: DockWebSocketClient | None = None
        self._ws_password: str = ""

        # IR data
        self._codesets: list[dict] = []

        # Detailed remotes (IR remote definitions with codesets)
        self._remotes: list[dict] = []

    # ------------------------------------------------------------------
    # Class method: construct from API dict
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        data: dict,
        *,
        api_key: str,
        remote_endpoint: str,
        remote_configuration_url: str = "",
    ) -> Dock:
        """Create a Dock from the dict returned by ``GET /docks``."""
        return cls(
            dock_id=data.get("entity_id", ""),
            api_key=api_key,
            remote_endpoint=remote_endpoint,
            remote_configuration_url=remote_configuration_url,
            name=data.get("name", ""),
            ws_url=data.get("ws_url", ""),
            is_active=data.get("active", False),
            model_number=data.get("model_number", ""),
            hardware_revision=data.get("hardware_revision", ""),
            serial_number=data.get("serial_number", ""),
            led_brightness=data.get("led_brightness", 0),
            ethernet_led_brightness=data.get("ethernet_led_brightness", 0),
            software_version=data.get("software_version", ""),
            state=data.get("state", ""),
            is_learning_active=data.get("learning_active", False),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def ws_url(self) -> str:
        """WebSocket URL for a direct connection to the dock."""
        return self._ws_url

    @property
    def learned_code(self) -> dict:
        """Most recently learned IR code (populated during a learning session)."""
        return self._learned_code

    @property
    def codesets(self) -> list[dict]:
        """Custom IR codesets stored on this dock."""
        return self._codesets

    @property
    def is_connected(self) -> bool:
        """``True`` when an active WebSocket connection to the dock is open."""
        return self._ws_client is not None and self._ws_client.is_connected

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def connect_websocket(
        self,
        password: str,
        *,
        message_callback: MessageCallback | None = None,
        reconnect_delay: float = 10.0,
    ) -> None:
        """Open a native WebSocket connection to the dock.

        Args:
            password: The dock token / password.
            message_callback: Optional async callable(raw_message: str).
            reconnect_delay: Seconds between reconnection attempts.
        """
        if not self._ws_url:
            _LOGGER.warning("Dock %s has no ws_url - cannot open WebSocket", self.device.id)
            return

        self._ws_password = password
        self._ws_client = DockWebSocketClient(
            self._ws_url, password, reconnect_delay=reconnect_delay
        )
        self._ws_client.on_message(self._handle_ws_message)
        if message_callback:
            self._ws_client.on_message(message_callback)

        await self._ws_client.connect()

    async def validate_password(self, password: str, *, timeout: float = 5.0) -> bool:
        """Return ``True`` if *password* is accepted by the dock WebSocket.

        Performs a short-lived connection test without keeping the socket open.

        Args:
            password: The password to validate.
            timeout: Seconds to wait for each handshake step.
        """
        if not self._ws_url:
            _LOGGER.warning("Dock %s has no ws_url - cannot validate password", self.device.id)
            return False
        return await DockWebSocketClient.validate(self._ws_url, password, timeout=timeout)

    async def disconnect_websocket(self) -> None:
        """Close the native WebSocket connection."""
        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None

    async def _handle_ws_message(self, raw: str) -> None:
        """Update dock state from received WebSocket messages."""

        try:
            data = json.loads(raw)
        except Exception:
            return

        msg_type = data.get("type") or data.get("msg", "")

        if msg_type == "dock_state":
            state = data.get("msg_data", {}).get("state", "")
            if state:
                self.state.state = state

        if msg_type == "software_update":
            msg_data = data.get("msg_data", {})
            event = msg_data.get("event_type", "")
            if event == "START":
                self.system.update_info.in_progress = True
            elif event == "PROGRESS":
                progress = msg_data.get("progress", {})
                self.system.update_info.update_percent = int(progress.get("current_percent", 0))
            elif event in ("DONE", "SUCCESS"):
                self.system.update_info.in_progress = False
                self.system.update_info.update_percent = 0

        if msg_type == "ir_learn":
            self._learned_code = data.get("msg_data", {})

    # ------------------------------------------------------------------
    # REST operations
    # ------------------------------------------------------------------

    async def get_info(self) -> dict:
        """Fetch detailed device information from the remote and update local state.

        Returns:
            Raw device info dict from ``GET /docks/devices/{id}``.
        """
        info = await self.api.get_dock_detail(self.device.id)
        self.device.name = info.get("name", self.device.name)
        self._ws_url = info.get("resolved_ws_url", self._ws_url)
        self.state.is_active = bool(info.get("active", self.state.is_active))
        self.device.model_number = info.get("model", self.device.model_number)
        self.device.hardware_revision = info.get("revision", self.device.hardware_revision)
        self.device.serial_number = info.get("serial", self.device.serial_number)
        self.state.led_brightness = int(info.get("led_brightness", self.state.led_brightness))
        self.state.ethernet_led_brightness = int(
            info.get("eth_led_brightness", self.state.ethernet_led_brightness)
        )
        self.device.software_version = info.get("version", self.device.software_version)
        self.state.state = info.get("state", self.state.state)
        self.state.is_learning_active = bool(
            info.get("learning_active", self.state.is_learning_active)
        )
        return info

    async def validate_connection(self) -> bool:
        """Check that the dock is reachable via the remote proxy.

        Returns:
            ``True`` if the dock device info can be retrieved successfully.
        """
        try:
            await self.api.get_dock_detail(self.device.id)
            return True
        except Exception:
            return False

    async def start_ir_learning(self) -> dict:
        """Start an IR learning session on this dock.

        Returns:
            Response dict from ``PUT /ir/emitters/{id}/learn``.
        """
        result = await self.api.put_ir_emitter_learn(self.device.id)
        self.state.is_learning_active = True
        return result

    async def stop_ir_learning(self) -> None:
        """Stop an active IR learning session on this dock."""
        await self.api.delete_ir_emitter_learn(self.device.id)
        self.state.is_learning_active = False

    async def get_remotes(self) -> list[dict]:
        """Return IR remote definitions stored on the remote.

        Returns:
            Raw list of remote definition dicts from the API.
        """
        return await self.api.get_remotes()

    async def get_remotes_complete(self) -> list[dict]:
        """Return IR remote definitions with full codeset details.

        Fetches the basic remote list then enriches each entry with
        detailed information (including codeset name and commands).

        Returns:
            List of enriched remote definition dicts.
        """
        remotes = await self.get_remotes()
        complete: list[dict] = []
        for r in remotes:
            entity_id = r.get("entity_id", "")
            try:
                detail = await self.get_remote_by_id(entity_id) if entity_id else r
                complete.append(detail)
            except Exception:
                complete.append(r)
        self._remotes = complete
        return complete

    @property
    def remotes_complete(self) -> list[dict]:
        """Cached result of the last :meth:`get_remotes_complete` call."""
        return self._remotes

    async def get_remote_by_id(self, entity_id: str) -> dict:
        """Return full IR remote definition for a given entity ID.

        Args:
            entity_id: The remote entity ID.

        Returns:
            Full remote definition dict from the API.
        """
        return await self.api.get_remote(entity_id)

    async def get_custom_codesets(self) -> list[dict]:
        """Return user-defined custom IR codesets from the remote.

        Populates :attr:`_codesets` and returns the raw list.
        """
        self._codesets = await self.api.get_ir_custom_codes()
        return self._codesets

    async def delete_custom_codeset(self, codeset_device_id: str) -> None:
        """Delete a custom IR codeset.

        Args:
            codeset_device_id: The device ID of the codeset to delete.
        """
        await self.api.delete_ir_custom_code(codeset_device_id)

    async def create_remote(
        self,
        name: str,
        device: str,
        description: str,
        icon: str = "uc:movie",
    ) -> dict:
        """Create a new IR remote definition on the remote.

        Args:
            name: Human-readable name for the remote.
            device: Device name for the custom codeset.
            description: Short description of the remote.
            icon: Icon identifier (default ``"uc:movie"``).

        Returns:
            Newly created remote definition dict.
        """
        body = {
            "name": {"en": name},
            "icon": icon,
            "description": {"en": description},
            "custom_codeset": {
                "manufacturer_id": "custom",
                "device_name": device,
                "device_type": "various",
            },
        }
        return await self.api.post_remote(body)

    async def add_remote_command_to_codeset(
        self,
        remote_entity_id: str,
        command_id: str,
        value: str,
        ir_format: str,
        *,
        update_if_exists: bool = True,
    ) -> dict:
        """Add an IR command to an existing remote codeset.

        If the command already exists and *update_if_exists* is ``True``,
        the command is updated instead of raising an error.

        Args:
            remote_entity_id: The remote entity ID.
            command_id: The command identifier.
            value: The IR code value string.
            ir_format: Format string (e.g. ``"HEX"`` or ``"PRONTO"``).
            update_if_exists: Whether to update if the command already exists.

        Returns:
            The added or updated command dict.
        """
        body = {"value": value, "format": ir_format}
        try:
            return await self.api.post_remote_ir_command(remote_entity_id, command_id, body)
        except HTTPError as exc:
            if exc.status_code == 422 and update_if_exists:
                return await self.update_remote_command_in_codeset(
                    remote_entity_id, command_id, value, ir_format
                )
            raise

    async def update_remote_command_in_codeset(
        self,
        remote_entity_id: str,
        command_id: str,
        value: str,
        ir_format: str,
    ) -> dict:
        """Update an existing IR command in a remote codeset.

        Args:
            remote_entity_id: The remote entity ID.
            command_id: The command identifier.
            value: The new IR code value string.
            ir_format: Format string (e.g. ``"HEX"`` or ``"PRONTO"``).

        Returns:
            The updated command dict.
        """
        body = {"value": value, "format": ir_format}
        return await self.api.patch_remote_ir_command(remote_entity_id, command_id, body)

    async def update(self) -> None:
        """Refresh dock state by fetching info and update status."""
        try:
            await self.get_info()
        except Exception as exc:
            _LOGGER.debug("Dock.update get_info error: %s", exc)
        try:
            await self.system.get_update_status()
        except Exception as exc:
            _LOGGER.debug("Dock.update get_update_status error: %s", exc)

    async def close(self) -> None:
        """Release all resources held by this dock."""
        await self.disconnect_websocket()
        await self.api.close()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Dock:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


@dataclass
class DeviceInfo:
    """Device information for a Dock, from ``GET /docks/{id}``."""

    id: str = ""
    _name: str = ""
    model_number: str = ""
    hardware_revision: str = ""
    serial_number: str = ""
    manufacturer: str = "Unfolded Circle"
    software_version: str = ""
    ip_address: str = ""

    @property
    def name(self) -> str:
        """Human-readable dock name."""
        return self._name or "Unfolded Circle Dock"

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def model_name(self) -> str:
        """Marketing model name derived from the model number."""
        if self.model_number == "UCD2":
            return "Dock Two"
        if self.model_number == "UCD3":
            return "Dock 3"
        return self.model_number or "Unfolded Circle Dock"

    @property
    def mac_address(self) -> str:
        """MAC address derived from the dock ID."""
        return self.id.lower().removeprefix("uc-dock-")


@dataclass
class DockState:
    """Current state of the dock."""

    is_active: bool = False
    state: str = ""
    led_brightness: int = 0
    ethernet_led_brightness: int = 0
    is_learning_active: bool = False


class System:
    """System-level state and operations for a dock."""

    def __init__(self, dock: Dock) -> None:
        self.update_info = UpdateInfo()
        self._dock = dock

    @property
    def _api(self) -> CoreAPI:
        """Shortcut to the parent remote's :class:`~unfurled.api.CoreAPI` client."""
        return self._dock.api

    async def _send_command(self, command: DockCommand, **params: object) -> dict:
        """Send a control command to the dock via the remote's API.

        Args:
            command: A :class:`~unfurled.models.DockCommand` value.
            **params: Additional parameters included in the request body.
        """
        body: dict = {"cmd": command.value, **params}
        return await self._api.post_dock_command(self._dock.device.id, body)

    async def set_led_brightness(self, brightness: int) -> None:
        """Set the dock LED brightness.

        Args:
            brightness: Brightness level 0-100.
        """
        await self._send_command(DockCommand.SET_LED_BRIGHTNESS, brightness=brightness)
        self._dock.state.led_brightness = brightness

    async def identify(self) -> None:
        """Flash the dock LEDs to visually identify this unit."""
        await self._send_command(DockCommand.IDENTIFY)

    async def reboot(self) -> None:
        """Reboot the dock."""
        await self._send_command(DockCommand.REBOOT)

    async def get_update_status(self) -> dict:
        """Fetch firmware update status and update local state.

        Returns:
            Raw update status dict from ``GET /docks/devices/{id}/update``.
        """
        info = await self._dock.api.get_dock_update_status(self._dock.device.id)
        self.update_info.latest_version = info.get("version", "")
        self.update_info.available = info.get("update_available", [])
        self._dock.settings.software_update.check_for_updates = bool(
            info.get("update_check_enabled", False)
        )
        return info

    async def update_firmware(self) -> dict:
        """Trigger a firmware update for the dock.

        Returns:
            Response dict which includes a ``state`` key.  The state may be
            ``"DOWNLOADING"``, ``"NO_BATTERY"``, or the response from the
            firmware update endpoint on success.
        """
        try:
            info = await self._api.post_dock_update(self._dock.device.id)
            self.update_info.in_progress = True
            return info
        except HTTPError as exc:
            if exc.status_code == 409:
                return {"state": "DOWNLOADING"}
            if exc.status_code == 503:
                return {"state": "NO_BATTERY"}
            raise


@dataclass
class SoftwareUpdateSettings:
    """Settings related to software updates."""

    check_for_updates: bool = True
    auto_download: bool = False
    auto_install: bool = False


class Settings:
    """Aggregated settings for a dock."""

    def __init__(self) -> None:
        self.software_update = SoftwareUpdateSettings()
