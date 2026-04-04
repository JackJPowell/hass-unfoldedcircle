"""Infrared platform for Unfolded Circle Remote Integration.

Exposes IR emitters as HA InfraredEntity objects so other integrations
(e.g. LG, Samsung) can target them via the infrared helper.

Three emitter types are handled:

1. DOCK  – one entity for the dock itself (default/all-outputs port) plus one
            entity per named port.  Each entity is attached to the dock's
            sub-device in the device registry.
2. Remote built-in IR – created when the remote's ``internal_ir`` feature is
            enabled.  Attached to the main remote device.
3. EXTERNAL – third-party emitters added via a driver on the remote (e.g.
            Broadlink).  One entity per external emitter, attached to the main
            remote device.
"""

from __future__ import annotations

import logging
from typing import Any

from infrared_protocols import Command as InfraredCommand

from homeassistant.components.infrared import InfraredEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UnfoldedCircleConfigEntry
from .coordinator import UnfoldedCircleDockCoordinator, UnfoldedCircleRemoteCoordinator
from .entity import UnfoldedCircleDockEntity, UnfoldedCircleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UnfoldedCircleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Unfolded Circle IR emitter entities."""
    coordinator = config_entry.runtime_data.coordinator
    remote_api = coordinator.api
    entities: list[InfraredEntity] = []

    # ── 1. DOCK emitters ──────────────────────────────────────────────────────
    for subentry_id, dock_coordinator in config_entry.runtime_data.docks.items():
        subentry = config_entry.subentries[subentry_id]
        dock_id = subentry.data["id"]

        # Find the matching emitter in the remote's emitter list
        dock_emitter = next(
            (
                e
                for e in remote_api.ir_emitters
                if e.get("device_id") == dock_id and e.get("type") == "DOCK"
            ),
            None,
        )
        if dock_emitter is None:
            _LOGGER.debug(
                "No active DOCK IR emitter found for dock %s, skipping", dock_id
            )
            continue

        ports: list[dict[str, Any]] = dock_emitter.get("ports", [])

        for port in ports:
            port_id = port.get("port_id")
            port_name = port.get("name", f"Port {port_id}")
            entities.append(
                DockPortInfraredEntity(
                    coordinator=dock_coordinator,
                    config_entry=config_entry,
                    subentry=subentry,
                    emitter_device_id=dock_id,
                    port_id=port_id,
                    port_name=port_name,
                )
            )

        async_add_entities(
            [e for e in entities if isinstance(e, DockPortInfraredEntity)],
            config_subentry_id=subentry_id,
        )
        entities = [e for e in entities if not isinstance(e, DockPortInfraredEntity)]

    # ── 2. Remote built-in IR emitter ────────────────────────────────────────
    internal_emitter = next(
        (e for e in remote_api.ir_emitters if e.get("type") == "INTERNAL"),
        None,
    )
    if internal_emitter is not None:
        entities.append(
            RemoteInternalInfraredEntity(
                coordinator=coordinator, emitter=internal_emitter
            )
        )

    # ── 3. External / third-party emitters ───────────────────────────────────
    for emitter in remote_api.ir_emitters:
        if emitter.get("type") != "EXTERNAL":
            continue
        ports = emitter.get("ports", [])
        if ports:
            for port in ports:
                entities.append(
                    ExternalInfraredEntity(
                        coordinator=coordinator,
                        emitter=emitter,
                        port_id=port.get("port_id"),
                        port_name=port.get("name", f"Port {port.get('port_id')}"),
                    )
                )
        else:
            # No ports defined — send without a port_id
            entities.append(
                ExternalInfraredEntity(
                    coordinator=coordinator,
                    emitter=emitter,
                    port_id=None,
                    port_name=None,
                )
            )

    if entities:
        async_add_entities(entities)


# ── Entity implementations ────────────────────────────────────────────────────


class DockPortInfraredEntity(UnfoldedCircleDockEntity, InfraredEntity):
    """IR emitter entity for a specific port on an Unfolded Circle Dock.

    One entity is created per port (including the "Default (all outputs)" port).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        config_entry: UnfoldedCircleConfigEntry,
        subentry: ConfigSubentry,
        emitter_device_id: str,
        port_id: str,
        port_name: str,
    ) -> None:
        super().__init__(coordinator, config_entry, subentry)
        self._emitter_device_id = emitter_device_id
        self._port_id = port_id
        self._attr_name = port_name
        self._attr_unique_id = (
            f"{subentry.unique_id}_ir_{emitter_device_id}_port_{port_id}"
        )

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Transmit an IR command through this dock port."""
        timings = command.get_raw_timings()
        # Convert raw timings to a HEX/PRONTO string the UC API understands.
        # The UC API accepts a raw Pronto-style hex string when format="PRONTO".
        hex_code = _timings_to_pronto(command.modulation, timings)
        try:
            remote_api = self.entry.runtime_data.coordinator.api
            await remote_api.send_ir_command_by_emitter(
                emitter_id=self._emitter_device_id,
                code=hex_code,
                format="PRONTO",
                port_id=self._port_id,
                repeat=getattr(command, "repeat_count", 0),
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to send IR command to dock port {self._port_id}: {err}"
            ) from err


class RemoteInternalInfraredEntity(UnfoldedCircleEntity, InfraredEntity):
    """IR emitter entity for the Unfolded Circle Remote's built-in emitter.

    The emitter entry has type=="INTERNAL" and device_id=="internal".
    It is only present in _ir_emitters when the feature is enabled on the remote.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnfoldedCircleRemoteCoordinator,
        emitter: dict,
    ) -> None:
        UnfoldedCircleEntity.__init__(self, coordinator)
        self._emitter = emitter
        self._attr_unique_id = f"{coordinator.api.model_number}_{coordinator.api.serial_number}_internal_ir"
        self._attr_name = "Internal IR Emitter"

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Transmit an IR command through the remote's built-in emitter."""
        timings = command.get_raw_timings()
        hex_code = _timings_to_pronto(command.modulation, timings)
        emitter_id: str = self._emitter.get("device_id", "internal")
        # Use the first port (typically the only one: port_id="1", name="Default")
        ports: list[dict] = self._emitter.get("ports", [])
        port_id: str | None = ports[0].get("port_id") if ports else None
        try:
            await self.coordinator.api.send_ir_command_by_emitter(
                emitter_id=emitter_id,
                code=hex_code,
                format="PRONTO",
                port_id=port_id,
                repeat=getattr(command, "repeat_count", 0),
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to send IR command via internal emitter: {err}"
            ) from err


class ExternalInfraredEntity(UnfoldedCircleEntity, InfraredEntity):
    """IR emitter entity for a specific port on a third-party emitter connected to the remote.

    External emitters (e.g. Broadlink RM Pro) are added via driver integrations
    on the remote.  One entity is created per port.  They are attached to the
    main remote device.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnfoldedCircleRemoteCoordinator,
        emitter: dict[str, Any],
        port_id: str | None,
        port_name: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._emitter = emitter
        self._port_id = port_id
        device_id: str = emitter.get("device_id", "")
        emitter_name: str = emitter.get("name", "External IR Emitter")
        uid_port = f"_port_{port_id}" if port_id is not None else ""
        self._attr_unique_id = (
            f"{coordinator.api.model_number}_{coordinator.api.serial_number}"
            f"_ext_ir_{device_id}{uid_port}"
        )
        self._attr_name = f"{emitter_name} {port_name}" if port_name else emitter_name

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Transmit an IR command through this external emitter port."""
        timings = command.get_raw_timings()
        hex_code = _timings_to_pronto(command.modulation, timings)
        emitter_id: str = self._emitter.get("device_id", "")
        try:
            await self.coordinator.api.send_ir_command_by_emitter(
                emitter_id=emitter_id,
                code=hex_code,
                format="PRONTO",
                port_id=self._port_id,
                repeat=getattr(command, "repeat_count", 0),
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to send IR command via external emitter '{self._attr_name}': {err}"
            ) from err


# ── Utility ───────────────────────────────────────────────────────────────────


def _timings_to_pronto(modulation: int, timings) -> str:
    """Convert raw infrared_protocols timings to a Pronto hex string.

    The Pronto format is: ``0000 <freq_code> <burst_pairs> 0000 <on1> <off1> ...``
    where the frequency code = round(1_000_000 / (modulation * 0.241246)).
    """
    freq_code = round(1_000_000 / (modulation * 0.241246)) if modulation else 0
    # Each Timing has .on and .off in microseconds; convert to Pronto clock units
    # (1 unit = 1 / (modulation Hz) seconds = 1e6/modulation µs)
    unit_us = 1_000_000 / modulation if modulation else 1
    pairs: list[str] = []
    for t in timings:
        on_units = max(1, round(t.high_us / unit_us))
        off_units = max(1, round(t.low_us / unit_us))
        pairs.append(f"{on_units:04X}")
        pairs.append(f"{off_units:04X}")
    burst_pairs = len(timings)
    header = f"0000 {freq_code:04X} {burst_pairs:04X} 0000"
    return header + " " + " ".join(pairs)
