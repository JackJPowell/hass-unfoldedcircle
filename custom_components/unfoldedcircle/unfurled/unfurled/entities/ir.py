"""IR emitter and codeset domain classes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..helpers.exceptions import InvalidIRFormat, NoEmitterFound
from ..submodules.base import RemoteModule

if TYPE_CHECKING:
    from ..dock import Dock
    from ..remote import Remote

_LOGGER = logging.getLogger(__name__)


@dataclass
class IRCode:
    """A single IR command code within a codeset.

    Mirrors the ``codes[]`` entries from ``GET /api/remotes/{id}/ir``.
    """

    cmd_id: str
    value: str
    format: str = "HEX"
    custom: bool = False
    modified: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> IRCode:
        """Construct an :class:`IRCode` from a raw API ``codes[]`` entry."""
        code = data.get("code", data)
        return cls(
            cmd_id=data.get("cmd_id", data.get("key", "")),
            value=code.get("value", ""),
            format=code.get("format", "HEX"),
            custom=bool(data.get("custom", False)),
            modified=bool(data.get("modified", False)),
        )


@dataclass
class IRCodeset:
    """An IR codeset associated with an IR remote device.

    Mirrors the ``GET /api/remotes/{id}/ir`` response object.
    """

    id: str
    name: str
    type: str = "manufacturer"
    codes: list[IRCode] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> IRCodeset:
        """Construct an :class:`IRCodeset` from a raw API response dict."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", "manufacturer"),
            codes=[IRCode.from_dict(c) for c in data.get("codes", [])],
        )


@dataclass
class IRCustomCode:
    """A user-defined custom IR codeset reference.

    Mirrors the ``ir_custom_codeset`` object returned by the API.
    """

    manufacturer_id: str = ""
    manufacturer: str = ""
    device_id: str = ""
    device: str = ""
    device_type: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> IRCustomCode:
        """Construct an :class:`IRCustomCode` from a raw API response dict."""
        return cls(
            manufacturer_id=data.get("manufacturer_id", ""),
            manufacturer=data.get("manufacturer", ""),
            device_id=data.get("device_id", ""),
            device=data.get("device", ""),
            device_type=data.get("device_type", ""),
        )


class IREmitter:
    """Represents a physical IR emitter (dock or built-in).

    Allows sending raw IR codes or predefined codeset commands.
    """

    def __init__(self, data: dict, remote: Remote) -> None:
        self._remote = remote
        self._device_id: str = data.get("device_id", "")
        self._name: str = data.get("name", "")
        self._type: str = data.get("type", "")
        self._state: str = data.get("state", "")
        self._ports: list[dict] = data.get("ports", [])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        """Unique device identifier for this emitter."""
        return self._device_id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return self._name

    @property
    def type(self) -> str:
        """Emitter type string (e.g. ``"DOCK"`` or ``"INTERNAL"``)."""
        return self._type

    @property
    def state(self) -> str:
        """Current emitter state (e.g. ``"CONNECTED"`` or ``"IDLE"``)."""
        return self._state

    @property
    def ports(self) -> list[dict]:
        """Output ports exposed by this emitter."""
        return self._ports

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def send_code(
        self,
        code: str,
        ir_format: str,
        *,
        port_id: str | None = None,
        repeat: int = 0,
    ) -> bool:
        """Send a raw HEX or PRONTO IR code via this emitter.

        Args:
            code: The IR code string.
            port_id: Optional output port ID.
            repeat: Number of additional repeats.

        Returns:
            ``True`` on success.
        """
        await self._remote._ensure_awake()
        body: dict = {"code": code, "format": ir_format}
        if port_id:
            body["port_id"] = port_id
        if repeat > 0:
            body["repeat"] = repeat
        await self._remote.api.put_ir_send(self._device_id, body)
        return True

    async def send_codeset_command(
        self,
        codeset_id: str,
        cmd_id: str,
        *,
        port_id: str | None = None,
        repeat: int = 0,
    ) -> bool:
        """Send a predefined codeset command via this emitter.

        Args:
            codeset_id: The codeset identifier.
            cmd_id: The command within the codeset.
            port_id: Optional output port ID.
            repeat: Number of additional repeats.

        Returns:
            ``True`` on success.
        """
        await self._remote._ensure_awake()
        body: dict = {"codeset_id": codeset_id, "cmd_id": cmd_id}
        if port_id:
            body["port_id"] = port_id
        if repeat > 0:
            body["repeat"] = repeat
        await self._remote.api.put_ir_send(self._device_id, body)
        return True


class IR(RemoteModule):
    """IR command dispatch, emitter resolution, and codeset/manufacturer lookup.

    Accessed via ``remote.ir``.

    Example::

        await remote.ir.send("0000 006C ...")
        await remote.ir.send("VOLUME_UP", device="Samsung TV")
    """

    @property
    def emitters(self) -> list[IREmitter]:
        """IR emitters discovered during :meth:`~unfurled.remote.Remote.init`."""
        return self._remote.ir_emitters

    @property
    def codesets(self) -> list[IRCodeset]:
        """Loaded IR codesets for all registered IR remotes."""
        return self._remote.ir_codesets

    def get_emitter(self, name: str) -> IREmitter | None:
        """Return the emitter with the given name (case-insensitive), or ``None``."""
        return next((e for e in self.emitters if e.name.lower() == name.lower()), None)

    def _resolve(
        self,
        name: str | None,
        device_id: str | None,
    ) -> IREmitter:
        """Resolve an emitter by name, device ID, or default to the first available."""

        if device_id:
            emitter: IREmitter | None = next(
                (e for e in self.emitters if e.device_id == device_id), None
            )
        elif name:
            emitter = self.get_emitter(name)
        elif self.emitters:
            emitter = self.emitters[0]
        else:
            emitter = None
        if emitter is None:
            raise NoEmitterFound("No IR emitter matches the supplied criteria")
        return emitter

    async def send(
        self,
        command: str,
        *,
        device: str | None = None,
        codeset: str | None = None,
        emitter_name: str | None = None,
        emitter_id: str | None = None,
        port_id: str | None = None,
        repeat: int = 0,
        dock: Dock | None = None,
    ) -> bool:
        """Resolve and send raw, custom, or loaded-codeset IR commands."""
        raw_command = self._parse_raw_command(command)
        if raw_command is not None:
            return await self._send_raw(
                *raw_command,
                emitter_name=emitter_name,
                emitter_id=emitter_id,
                port_id=port_id,
                repeat=repeat,
                dock=dock,
            )

        if device and codeset:
            return await self._send_from_manufacturer(
                device,
                codeset,
                command,
                emitter_name=emitter_name,
                emitter_id=emitter_id,
                port_id=port_id,
                repeat=repeat,
            )

        if device:
            custom_code = await self.get_custom_code(device, command)
            if custom_code is not None:
                return await self._send_raw(
                    custom_code.value,
                    custom_code.format,
                    emitter_name=emitter_name,
                    emitter_id=emitter_id,
                    port_id=port_id,
                    repeat=repeat,
                    dock=dock,
                )

        codeset_name = codeset or device
        if not codeset_name:
            raise InvalidIRFormat("IR command must be raw or include a custom device or codeset")
        return await self._send_from_codeset(
            codeset_name,
            command,
            emitter_name=emitter_name,
            emitter_id=emitter_id,
            port_id=port_id,
            repeat=repeat,
        )

    async def send_raw(
        self,
        code: str,
        *,
        emitter_name: str | None = None,
        emitter_id: str | None = None,
        port_id: str | None = None,
        repeat: int = 0,
        dock: Dock | None = None,
    ) -> bool:
        """Send a raw Pronto or HEX IR code, inferring its format."""
        raw_command = self._parse_raw_command(code)
        if raw_command is None:
            raise InvalidIRFormat("Raw IR code must be Pronto or UC HEX format")
        return await self._send_raw(
            *raw_command,
            emitter_name=emitter_name,
            emitter_id=emitter_id,
            port_id=port_id,
            repeat=repeat,
            dock=dock,
        )

    @staticmethod
    def _parse_raw_command(command: str) -> tuple[str, str] | None:
        """Return a raw command and its format, if *command* is raw IR."""
        if command.startswith("0000"):
            return command, "PRONTO"
        if re.fullmatch(r"\d+;0x[0-9A-Fa-f]+;\d+;\d+", command):
            return command, "HEX"
        return None

    async def _send_raw(
        self,
        code: str,
        ir_format: str,
        *,
        emitter_name: str | None,
        emitter_id: str | None,
        port_id: str | None,
        repeat: int,
        dock: Dock | None,
    ) -> bool:
        """Send resolved raw IR through a dock or remote emitter."""
        if dock is not None:
            return await dock.send_ir(code, ir_format, port_mask=port_id, repeat=repeat)
        await self._ensure_awake()
        emitter = self._resolve(emitter_name, emitter_id)
        return await emitter.send_code(code, ir_format, port_id=port_id, repeat=repeat)

    async def _send_from_manufacturer(
        self,
        manufacturer_name: str,
        codeset_name: str,
        command: str,
        *,
        emitter_name: str | None,
        emitter_id: str | None,
        port_id: str | None,
        repeat: int,
    ) -> bool:
        """Resolve and send a command from a manufacturer codeset."""
        await self._ensure_awake()
        manufacturers = await self._remote.api.get_ir_manufacturers(q=manufacturer_name)
        manufacturer = next(
            (
                item
                for item in manufacturers
                if item.get("name", "").casefold() == manufacturer_name.casefold()
            ),
            manufacturers[0] if manufacturers else None,
        )
        if manufacturer is None:
            raise InvalidIRFormat(f"IR manufacturer {manufacturer_name} was not found")

        manufacturer_id = manufacturer.get("id", "")
        codesets = await self._remote.api.get_ir_manufacturer_codesets(
            manufacturer_id, q=codeset_name
        )
        codeset = next(
            (
                item
                for item in codesets
                if item.get("name", "").casefold() == codeset_name.casefold()
            ),
            codesets[0] if codesets else None,
        )
        if codeset is None:
            raise InvalidIRFormat(
                f"IR codeset {codeset_name} was not found for manufacturer {manufacturer_name}"
            )

        codeset_id = codeset.get("id", "")
        commands = await self._remote.api.get_ir_manufacturer_codeset_commands(
            manufacturer_id, codeset_id
        )
        cmd_id = next((item for item in commands if item.casefold() == command.casefold()), None)
        if cmd_id is None:
            raise InvalidIRFormat(f"IR command {command} was not found in codeset {codeset_name}")

        emitter = self._resolve(emitter_name, emitter_id)
        return await emitter.send_codeset_command(
            codeset_id, cmd_id, port_id=port_id, repeat=repeat
        )

    async def _send_from_codeset(
        self,
        codeset_name: str,
        command: str,
        *,
        emitter_name: str | None,
        emitter_id: str | None,
        port_id: str | None,
        repeat: int,
    ) -> bool:
        """Send a named command from a loaded codeset."""
        await self._ensure_awake()
        ir_codeset = next((c for c in self.codesets if c.name == codeset_name), None)
        if not ir_codeset:
            raise InvalidIRFormat(f"IR device '{codeset_name}' not found in loaded codesets")
        emitter = self._resolve(emitter_name, emitter_id)
        return await emitter.send_codeset_command(
            ir_codeset.id, command, port_id=port_id, repeat=repeat
        )

    async def get_custom_code(self, device: str, command: str) -> IRCode | None:
        """Resolve a command from a user-defined custom IR device."""
        custom_devices = await self._remote.api.get_ir_custom_codes()
        custom_device = next(
            (
                item
                for item in custom_devices
                if item.get("device", "").casefold() == device.casefold()
            ),
            None,
        )
        if custom_device is None:
            return None

        detail = await self._remote.api.get_ir_custom_codeset(custom_device.get("device_id", ""))
        code = next(
            (
                item
                for item in detail.get("codes", [])
                if item.get("key", "").casefold() == command.casefold()
            ),
            None,
        )
        if code is None:
            raise InvalidIRFormat(
                f"IR command '{command}' was not found for custom device '{device}'"
            )
        return IRCode.from_dict(code)

    async def send_by_emitter(
        self,
        emitter_id: str,
        code: str,
        *,
        port_id: str | None = None,
        repeat: int = 0,
    ) -> bool:
        """Send a raw IR code directly to a specific emitter device ID.

        Convenience wrapper around :meth:`send` when you already know the
        emitter's ``device_id`` and prefer positional arguments.

        Args:
            emitter_id: The ``device_id`` of the target IR emitter.
            code: IR code string (HEX or PRONTO).
            port_id: Optional output port ID.
            repeat: Number of additional repeats.
        """
        return await self.send_raw(code, emitter_id=emitter_id, port_id=port_id, repeat=repeat)
