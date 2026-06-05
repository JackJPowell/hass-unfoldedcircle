"""Shared base class for Remote domain sub-objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api import CoreAPI
    from ..remote import Remote


class RemoteModule:
    """Base for domain-specific objects composed onto a :class:`~unfurled.remote.Remote`.

    Subclasses gain a ``_remote`` back-reference, a ``_api`` shortcut, and
    ``_ensure_awake()`` so every domain module can guard commands without
    duplicating the wake-up logic.
    """

    __slots__ = ("_remote",)

    def __init__(self, remote: Remote) -> None:
        self._remote = remote

    @property
    def _api(self) -> CoreAPI:
        """Shortcut to the parent remote's :class:`~unfurled.api.CoreAPI` client."""
        return self._remote.api

    async def _ensure_awake(self) -> None:
        """Proxy to :meth:`Remote._ensure_awake`; wakes the device if needed."""
        await self._remote._ensure_awake()
