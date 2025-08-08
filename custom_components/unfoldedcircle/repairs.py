"""Unfolded Circle Repairs"""

from __future__ import annotations
import logging
import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.helpers import issue_registry
from homeassistant.core import HomeAssistant
from .helpers import (
    validate_dock_password,
    register_system_and_driver,
    get_ha_websocket_url,
    validate_websocket_address,
)
from .config_flow import CannotConnect, InvalidDockPassword
from .const import DOMAIN
from . import UnfoldedCircleConfigEntry
from .websocket import UCWebsocketClient


_LOGGER = logging.getLogger(__name__)


class DockPasswordRepairFlow(RepairsFlow):
    """Handler for an issue fixing flow."""

    def __init__(self, hass, issue_id, data) -> None:
        super().__init__()
        self.data = data
        self.issue_id = issue_id
        self.hass = hass
        self.config_entry: UnfoldedCircleConfigEntry = self.data.get("config_entry")
        self.subentry = self.data.get("subentry")
        self.coordinator = self.config_entry.runtime_data.coordinator

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Prompt the user to enter a dock password."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                dock_data = {
                    "id": self.data["id"],
                    "name": self.data["name"],
                    "password": user_input.get("password"),
                }
                is_valid = await validate_dock_password(self.coordinator.api, dock_data)
                if not is_valid:
                    raise InvalidDockPassword

                _LOGGER.debug("Updating dock password %s", dock_data.get("name"))

                self.hass.config_entries.async_update_subentry(
                    self.config_entry,
                    self.subentry,
                    data=dock_data,
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                issue_registry.async_delete_issue(self.hass, DOMAIN, self.issue_id)
                return self.async_abort(reason="reauth_successful")

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDockPassword:
                errors["base"] = "invalid_dock_password"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="confirm",
            errors=errors,
            data_schema=vol.Schema({vol.Required("password"): str}),
            description_placeholders={"name": self.data["name"]},
        )


class WebSocketRepairFlow(RepairsFlow):
    """Handler for an issue fixing flow."""

    def __init__(self, hass, issue_id, data) -> None:
        super().__init__()
        self.data = data
        self.issue_id = issue_id
        self.hass = hass
        self.config_entry: UnfoldedCircleConfigEntry = self.data.get("config_entry")
        self.coordinator = self.config_entry.runtime_data.coordinator

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if validate_websocket_address(user_input.get("websocket_url")):
                    await register_system_and_driver(
                        self.coordinator.api, self.hass, user_input.get("websocket_url")
                    )
                    websocket_client = UCWebsocketClient(self.hass)
                    configure_entities_subscription = (
                        websocket_client.get_driver_subscription(
                            self.coordinator.api.hostname
                        )
                    )
                    if not configure_entities_subscription:
                        raise WebsocketFailure
                    try:
                        await self.hass.config_entries.async_reload(
                            self.coordinator.config_entry.entry_id
                        )

                        issue_registry.async_delete_issue(
                            self.hass, DOMAIN, self.issue_id
                        )

                        return self.async_abort(reason="ws_connection_successful")
                    except Exception:
                        errors["base"] = "cannot_connect"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except WebsocketFailure:
                errors["base"] = "websocket_failure"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="confirm",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "websocket_url", default=get_ha_websocket_url(self.hass)
                    ): str
                }
            ),
            description_placeholders={"name": self.data["name"]},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("dock_password"):
        return DockPasswordRepairFlow(hass, issue_id, data)
    if issue_id == "websocket_connection":
        return WebSocketRepairFlow(hass, issue_id, data)


class WebsocketFailure(Exception):
    """Error to indicate there the creation of HA token failed."""
