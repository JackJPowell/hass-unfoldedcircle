"""System sub-object - hardware stats, feature flags, update info, and system operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..helpers.exceptions import HTTPError, SystemCommandNotFound
from ..helpers.models import (
    RemoteCommand,
    RemoteFeatureFlags,
    RemoteStats,
    SoftwareUpdateEvent,
    UpdateInfo,
    UpdateType,
)
from .base import RemoteModule

if TYPE_CHECKING:
    from ..remote import Remote

_LOGGER = logging.getLogger(__name__)


class System(RemoteModule):
    """Manages system-level state and operations.

    Accessed via ``remote.system``. Holds hardware capability flags, resource
    statistics, software update info, and standby inhibitor state. Also exposes
    operations for system commands, firmware updates, and wireless charging.

    Example::

        await remote.system.send_command("STANDBY")
        print(remote.system.stats.memory_available)
        await remote.system.refresh_standby_inhibitors()
    """

    def __init__(self, remote: Remote) -> None:
        super().__init__(remote)
        self.flags = RemoteFeatureFlags()
        self.stats = RemoteStats()
        self.update_info = UpdateInfo()
        self.standby_inhibitors: list[dict] = []

    # ------------------------------------------------------------------
    # Internal fetch helpers (called by Remote.init / update)
    # ------------------------------------------------------------------

    async def _fetch_stats(self) -> None:
        data = await self._api.get_pub_status()
        mem = data.get("memory", {})
        self.stats.memory_total = mem.get("total_memory", 0) / 1048576
        self.stats.memory_available = mem.get("available_memory", 0) / 1048576
        fs = data.get("filesystem", {}).get("user_data", {})
        self.stats.storage_total = (fs.get("used", 0) + fs.get("available", 0)) / 1048576
        self.stats.storage_available = fs.get("available", 0) / 1048576
        load = data.get("load_avg", {})
        self.stats.cpu_load_one = load.get("one", 0.0)
        self.stats.cpu_load_five = load.get("five", 0.0)
        self.stats.cpu_load_fifteen = load.get("fifteen", 0.0)

    async def _fetch_update_info(self) -> None:
        try:
            if self._remote.device.is_simulator:
                return
            data = await self._api.get_system_update()
            self.update_info.latest_version = data.get("version", "")
            self.update_info.release_notes_url = data.get("release_notes_url", "")
            self.update_info.release_notes = data.get("release_notes", "")
            self.update_info.next_check_date = data.get("next_check_date", "")
            self.update_info.available = data.get("updates", [])
        except HTTPError:
            pass

    async def _fetch_charger(self) -> None:
        data = await self._api.get_charger()
        self.flags.charging_options = data.get("features", [])
        self._remote.state.is_wireless_charging = bool(data.get("wireless_charging", False))
        self.flags.wireless_charging_enabled = bool(data.get("wireless_charging_enabled", False))

    # ------------------------------------------------------------------
    # WS event handler
    # ------------------------------------------------------------------

    def _on_software_update(self, event: SoftwareUpdateEvent) -> None:
        event_type = event.event_type
        progress = event.progress

        if event_type == "START":
            self.update_info.in_progress = True

        elif event_type == "PROGRESS":
            state = progress.get("state", "")
            total_steps = progress.get("total_steps", 1) or 1
            offset = round(100 / total_steps)
            pct_offset = offset / 100

            match state:
                case "START" | "RUN":
                    self.update_info.update_percent = 0
                case "PROGRESS":
                    step = progress.get("current_step", 1)
                    step_offset = offset * (step - 1)
                    self.update_info.update_percent = int(
                        pct_offset * progress.get("current_percent", 0) + step_offset
                    )
                case "SUCCESS":
                    self.update_info.update_percent = 100
                    self._remote.device.sw_version = self.update_info.latest_version
                case "DONE":
                    self.update_info.in_progress = False
                    self.update_info.update_percent = 0
                    self.update_info.download_percent = 0
                    self._remote.device.sw_version = self.update_info.latest_version
                case "DOWNLOAD":
                    self.update_info.download_percent = int(progress.get("download_percent", 0))
                case _:
                    self.update_info.in_progress = False
                    self.update_info.update_percent = 0

        self._remote._last_update_type = UpdateType.SOFTWARE

    # ------------------------------------------------------------------
    # System command operations
    # ------------------------------------------------------------------

    async def send_command(self, cmd: RemoteCommand | str) -> None:
        """Send a system command to the remote.

        Args:
            cmd: A :class:`~unfurled.helpers.models.RemoteCommand` value or its
                string equivalent (e.g. ``RemoteCommand.STANDBY`` or ``"STANDBY"``)

        Raises:
            :class:`~unfurled.exceptions.SystemCommandNotFound`: if ``cmd`` is invalid.
        """
        try:
            cmd = RemoteCommand(cmd)
        except ValueError:
            raise SystemCommandNotFound(cmd)
        await self._ensure_awake()
        await self._api.post_system_command(cmd)

    async def reboot(self) -> None:
        """Reboot the remote."""
        await self.send_command(RemoteCommand.REBOOT)

    async def standby(self) -> None:
        """Put the remote into standby mode."""
        await self.send_command(RemoteCommand.STANDBY)

    async def power_off(self) -> None:
        """Power off the remote."""
        await self.send_command(RemoteCommand.POWER_OFF)

    async def restart(self) -> None:
        """Restart the remote."""
        await self.send_command(RemoteCommand.RESTART)

    # ------------------------------------------------------------------
    # Firmware update operations
    # ------------------------------------------------------------------

    async def get_update_status(self) -> dict:
        """Return the latest software update status from the remote."""
        return await self._api.get_system_update_latest()

    async def update_firmware(self, *, download_only: bool = False) -> str:
        """Trigger a firmware update.

        If *download_only* is ``True``, only downloads the update (does not
        install) — the update must be in ``PENDING`` or ``ERROR`` state first.
        """
        if download_only:
            status = await self.get_update_status()
            if status.get("state") not in ("PENDING", "ERROR"):
                return status.get("state", "UNKNOWN")

        data = await self._api.post_system_update_latest()
        return data.get("state", "UNKNOWN") if data else "OK"

    async def force_update_check(self) -> dict:
        """Force the remote to check for firmware updates immediately.

        Returns:
            Update information dict from the remote.
        """
        return await self._api.put_system_update()

    # ------------------------------------------------------------------
    # Wireless charging
    # ------------------------------------------------------------------

    async def set_wireless_charging(self, *, enabled: bool) -> None:
        """Enable or disable wireless charging (if supported)."""
        await self._ensure_awake()
        await self._api.put_wireless_charging(enabled)
        self.flags.wireless_charging_enabled = enabled

    # ------------------------------------------------------------------
    # Standby inhibitors
    # ------------------------------------------------------------------

    async def refresh_standby_inhibitors(self) -> list[dict]:
        """Refresh and return the list of active standby inhibitors."""
        await self._ensure_awake()
        self.standby_inhibitors = await self._api.get_standby_inhibitors()
        return self.standby_inhibitors

    async def set_standby_inhibitor(
        self, inhibitor_id: str, who: str, why: str, delay: int = 0
    ) -> None:
        """Register a standby inhibitor.

        Args:
            inhibitor_id: Unique identifier for this inhibitor.
            who: Name of the caller setting the inhibitor.
            why: Human-readable reason for the inhibitor.
            delay: Optional delay in seconds before the inhibitor takes effect.
        """
        await self._ensure_awake()
        body: dict = {"id": inhibitor_id, "who": who, "why": why}
        if delay:
            body["delay"] = delay
        await self._api.post_standby_inhibitor(body)

    async def remove_standby_inhibitor(self, inhibitor_id: str) -> None:
        """Remove a standby inhibitor by ID."""
        await self._ensure_awake()
        await self._api.delete_standby_inhibitor(inhibitor_id)

    async def remove_all_standby_inhibitors(self) -> None:
        """Remove all active standby inhibitors."""
        await self._ensure_awake()
        await self._api.delete_all_standby_inhibitors()
