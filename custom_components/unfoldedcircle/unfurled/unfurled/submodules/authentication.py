"""Authentication sub-object - API keys and external system tokens."""

from __future__ import annotations

from ..helpers.exceptions import ApiKeyError, ApiKeyNotFound, HTTPError
from .base import RemoteModule

_AUTH_APIKEY_NAME = "pyUnfoldedCircle"


class Authentication(RemoteModule):
    """Manages API keys and external system access tokens.

    Accessed via ``remote.auth``.

    Example::

        key = await remote.auth.create_key()
        await remote.auth.set_external_token("hass", "ws-ha-api", token)
    """

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    async def list_keys(self) -> list[dict]:
        """Return all API keys registered on the remote."""
        return await self._api.get_api_keys()

    async def create_key(self, name: str = _AUTH_APIKEY_NAME) -> str:
        """Create a new API key and update the remote's active key.

        Args:
            name: Human-readable name for the key.

        Returns:
            The new API key string.
        """
        data = await self._api.post_api_key(name, ["admin"])
        new_key = data.get("api_key", "")
        self._remote._api_key = new_key
        return new_key

    async def revoke_key(self, name: str = _AUTH_APIKEY_NAME) -> None:
        """Revoke the API key with the given name.

        Args:
            name: Name of the key to revoke.

        Raises:
            :class:`~unfurled.exceptions.ApiKeyNotFound`: if no key with that name exists.
        """
        keys = await self.list_keys()
        match = next((k for k in keys if k.get("name") == name), None)
        if not match:
            raise ApiKeyNotFound(name)
        await self._api.delete_api_key(match["key_id"])

    async def rotate_key(self, name: str = _AUTH_APIKEY_NAME) -> str:
        """Revoke the named key if it exists, then create a fresh one.

        Args:
            name: Key name to rotate.

        Returns:
            The new API key string.
        """
        try:
            keys = await self.list_keys()
            for key in keys:
                if key.get("name") == name:
                    await self._api.delete_api_key(key["key_id"])
        except Exception as exc:
            raise ApiKeyError("Failed to revoke existing key") from exc
        return await self.create_key(name)

    # ------------------------------------------------------------------
    # External system tokens
    # ------------------------------------------------------------------

    async def set_external_token(
        self,
        system: str,
        token_id: str,
        token: str,
        name: str = "Integration",
        *,
        description: str | None = None,
        url: str | None = None,
    ) -> dict:
        """Register or update an access token for an external integration.

        Creates the entry if it does not exist; falls back to PUT on a 422.

        Args:
            system: External system identifier (e.g. ``"hass"``).
            token_id: Unique token identifier within the system.
            token: The access token value.
            name: Human-readable name for the token.
            description: Optional description.
            url: Optional URL associated with the token.
        """
        body: dict = {"token_id": token_id, "name": name, "token": token}
        if description:
            body["description"] = description
        if url:
            body["url"] = url
        try:
            return await self._api.post_external_system_token(system, body)
        except HTTPError as exc:
            if exc.status_code == 422:
                return await self._api.put_external_system_token(system, token_id, body)
            raise

    async def update_external_token(
        self,
        system: str,
        token_id: str,
        token: str,
        name: str = "Integration",
        *,
        description: str | None = None,
        url: str | None = None,
    ) -> dict:
        """Update an existing access token for an external integration.

        Args:
            system: External system identifier (e.g. ``"hass"``).
            token_id: Unique token identifier within the system.
            token: The new access token value.
            name: Human-readable name for the token.
            description: Optional description.
            url: Optional URL associated with the token.
        """
        body: dict = {"token_id": token_id, "name": name, "token": token}
        if description:
            body["description"] = description
        if url:
            body["url"] = url
        return await self._api.put_external_system_token(system, token_id, body)

    async def delete_external_token(self, system: str, token_id: str) -> None:
        """Delete an access token for an external integration.

        Args:
            system: External system identifier.
            token_id: The token identifier to remove.
        """
        await self._ensure_awake()
        await self._api.delete_external_system_token(system, token_id)

    async def has_system(self, system: str) -> bool:
        """Return ``True`` if *system* is registered on the remote.

        Args:
            system: External system identifier to check.
        """
        registered = await self._api.get_external_systems()
        return any(rs.get("system") == system for rs in registered)

    async def system_has_token(self, system: str) -> bool:
        """Return ``True`` if the given external system has a token registered.

        Uses the ``ws-ha-api`` token ID convention from the Home Assistant integration.

        Args:
            system: External system identifier.
        """
        tokens = await self._api.get_external_system(system)
        return any(t.get("token_id") == "ws-ha-api" for t in tokens)
