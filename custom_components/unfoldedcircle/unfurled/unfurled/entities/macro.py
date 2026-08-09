"""Macro domain class."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..remote import Remote


class Macro:
    """A macro configured on an Unfolded Circle remote."""

    def __init__(self, data: dict, remote: Remote) -> None:
        self._remote = remote
        self._id: str = data.get("entity_id", "")
        self._name: str = remote.settings.get_text_for_locale(
            data.get("name", {}), default_text=self._id
        )
        self._description: str = remote.settings.get_text_for_locale(
            data.get("description", {}), default_text=""
        )
        self._enabled: bool = bool(data.get("enabled", True))
        self._features: list[str] = data.get("features", [])

    @property
    def id(self) -> str:
        """Unique entity ID."""
        return self._id

    @property
    def name(self) -> str:
        """Human-readable macro name."""
        return self._name

    @property
    def description(self) -> str:
        """Macro description."""
        return self._description

    @property
    def enabled(self) -> bool:
        """Whether the macro is enabled."""
        return self._enabled

    @property
    def features(self) -> list[str]:
        """Features exposed by the macro."""
        return self._features

    async def run(self) -> None:
        """Run this macro in the remote's active activity."""
        await self._remote._ensure_awake()
        await self._remote.api.put_entity_command(self._id, "macro.run")
