"""Integrations sub-object - integration instances and driver lifecycle."""

from __future__ import annotations

from ..api import IntegrationInstanceCommand
from ..helpers.exceptions import IntegrationNotFound
from .base import RemoteModule


class Integrations(RemoteModule):
    """Manages integration instances and driver setup flows.

    Accessed via ``remote.integrations``.

    Example::

        instance = await remote.integrations.get_by_driver("hass")
        await remote.integrations.send_command(instance["id"], IntegrationInstanceCommand.CONNECT)
    """

    async def get_by_driver(self, driver_id: str) -> dict:
        """Return the integration instance for the given driver ID.

        Args:
            driver_id: Driver identifier (e.g. ``"hass"``).

        Raises:
            :class:`~unfurled.exceptions.IntegrationNotFound`: if no matching instance exists.
        """
        instances = await self._api.get_integrations()
        match = next((i for i in instances if i.get("driver_id") == driver_id), None)
        if not match:
            raise IntegrationNotFound(f"No integration for driver '{driver_id}'")
        return match

    async def send_command(
        self,
        integration_id: str,
        cmd: IntegrationInstanceCommand | None = None,
    ) -> dict:
        """Send a lifecycle command to an integration instance.

        Args:
            integration_id: The integration instance ID.
            cmd: Command to send (e.g. ``CONNECT``, ``DISCONNECT``).
        """
        return await self._api.put_integration(integration_id, cmd)

    async def begin_setup(
        self,
        driver_id: str,
        *,
        reconfigure: bool = False,
        setup_data: dict | None = None,
    ) -> dict:
        """Start an integration driver setup flow.

        Args:
            driver_id: The driver to set up.
            reconfigure: If ``True``, reconfigure an existing instance.
            setup_data: Optional key/value pairs passed to the driver.
        """
        body: dict = {"driver_id": driver_id, "reconfigure": reconfigure}
        if setup_data:
            body["setup_data"] = setup_data
        return await self._api.post_integration_setup(body)
