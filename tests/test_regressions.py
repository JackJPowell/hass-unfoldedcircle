"""Regression coverage for registry lookups and repair reloads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, create_autospec, patch

import pytest

from custom_components.unfoldedcircle import _async_update_listener, async_remove_device
from custom_components.unfoldedcircle.const import DOMAIN
from custom_components.unfoldedcircle.coordinator import UnfoldedCircleDockCoordinator
from custom_components.unfoldedcircle.entity import UnfoldedCircleDockEntity
from custom_components.unfoldedcircle.helpers import validate_tokens
from custom_components.unfoldedcircle.issues import (
    async_create_issue_dock_password,
    async_create_issue_dock_unreachable,
    async_create_issue_websocket_connection,
    async_delete_issue_dock_unreachable,
    async_delete_legacy_issues,
    dock_password_issue_id,
    dock_unreachable_issue_id,
    websocket_connection_issue_id,
)
from custom_components.unfoldedcircle.repairs import (
    WebSocketRepairFlow,
    async_create_fix_flow,
)
from homeassistant.helpers.device_registry import DeviceRegistry


@pytest.fixture
def registry():
    """Enforce the installed Home Assistant registry API signatures."""
    registry = create_autospec(DeviceRegistry, instance=True)
    registry.async_get_device_by_identifier.return_value = SimpleNamespace(id="device")
    with patch(
        "homeassistant.helpers.device_registry.async_get", return_value=registry
    ):
        yield registry


def test_dock_entity_resolves_parent_in_own_entry(registry):
    """Dock entities retain the correct remote as their via device."""
    coordinator = Mock()
    entry = Mock(entry_id="remote-entry")
    remote = entry.runtime_data.coordinator.api.device
    entity = UnfoldedCircleDockEntity(coordinator, entry, Mock())
    registry.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, remote.model_number, remote.serial_number),
        config_entry_id="remote-entry",
    )
    assert entity.device_info["via_device_id"] == "device"


@pytest.mark.asyncio
async def test_dock_message_publishes_state(registry):
    """Registry metadata updates must not prevent publishing dock state."""
    coordinator = Mock(config_entry=Mock(entry_id="remote-entry"))
    coordinator.subentry.unique_id = "dock-id"
    await UnfoldedCircleDockCoordinator._on_dock_message(coordinator, "{}")
    registry.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, "dock-id"), config_entry_id="remote-entry"
    )
    registry.async_update_device.assert_called_once()
    coordinator.async_set_updated_data.assert_called_once_with({"updated": True})


@pytest.mark.asyncio
async def test_legacy_dock_removal_uses_own_entry(registry):
    """Migration removes the matching dock from the owning entry."""
    dock = Mock()
    await async_remove_device(Mock(), Mock(entry_id="remote-entry"), dock)
    registry.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, dock.device.model_number, dock.device.serial_number),
        config_entry_id="remote-entry",
    )
    registry.async_remove_device.assert_called_once_with("device")


@pytest.mark.asyncio
async def test_websocket_repair_schedules_reload_without_data_change():
    """Successful remote registration reloads even though entry data is unchanged."""
    hass = Mock()
    entry = Mock(entry_id="remote-entry", data={"host": "remote"})
    entry.runtime_data.coordinator.config_entry = entry
    issue_id = websocket_connection_issue_id(entry.entry_id)
    flow = WebSocketRepairFlow(hass, issue_id, {"config_entry": entry})
    with (
        patch(
            "custom_components.unfoldedcircle.repairs.register_system_and_driver",
            new_callable=AsyncMock,
        ),
        patch("custom_components.unfoldedcircle.repairs.UCWebsocketClient"),
        patch("custom_components.unfoldedcircle.repairs.async_delete_issue") as delete,
    ):
        result = await flow.async_step_confirm(
            {"websocket_url": "ws://localhost:8123/api/websocket"}
        )
    assert result["reason"] == "ws_connection_successful"
    hass.config_entries.async_schedule_reload.assert_called_once_with("remote-entry")
    hass.config_entries.async_reload.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()
    delete.assert_called_once_with(hass, issue_id)


def test_repair_issues_belong_to_their_config_entries():
    """Issue IDs and registry ownership isolate two remotes with the same dock ID."""
    from homeassistant.helpers import issue_registry

    hass = Mock()
    dock = Mock()
    dock.device.id = "dock-id"
    dock.device.name = "Dock"
    entry_one = Mock(entry_id="entry-one")
    entry_two = Mock(entry_id="entry-two")
    coordinator = Mock()
    coordinator.api.device.name = "Remote"

    with patch.object(issue_registry, "async_create_issue") as create:
        async_create_issue_dock_password(hass, dock, entry_one, Mock())
        async_create_issue_dock_unreachable(
            hass, dock, entry_two, Mock(), ConnectionError("offline")
        )
        async_create_issue_websocket_connection(hass, entry_one, coordinator)
        async_create_issue_websocket_connection(hass, entry_two, coordinator)

    calls = create.call_args_list
    assert [call.args[2] for call in calls] == [
        dock_password_issue_id("entry-one", "dock-id"),
        dock_unreachable_issue_id("entry-two", "dock-id"),
        websocket_connection_issue_id("entry-one"),
        websocket_connection_issue_id("entry-two"),
    ]
    assert [call.kwargs["config_entry_id"] for call in calls] == [
        "entry-one",
        "entry-two",
        "entry-one",
        "entry-two",
    ]


def test_legacy_issue_cleanup_preserves_entry_owned_issues():
    """Only old unowned IDs are removed when issue names change."""
    from homeassistant.helpers import issue_registry

    issues = {
        (DOMAIN, "websocket_connection"): SimpleNamespace(config_entry_id=None),
        (DOMAIN, "dock_password_dock-id"): SimpleNamespace(config_entry_id=None),
        (DOMAIN, "dock_unreachable_dock-id"): SimpleNamespace(config_entry_id=None),
        (
            DOMAIN,
            websocket_connection_issue_id("entry-one"),
        ): SimpleNamespace(config_entry_id="entry-one"),
        ("other", "websocket_connection"): SimpleNamespace(config_entry_id=None),
    }
    hass = Mock()
    with (
        patch.object(
            issue_registry, "async_get", return_value=SimpleNamespace(issues=issues)
        ),
        patch.object(issue_registry, "async_delete_issue") as delete,
    ):
        async_delete_legacy_issues(hass)

    assert {call.args for call in delete.call_args_list} == {
        (hass, DOMAIN, "websocket_connection"),
        (hass, DOMAIN, "dock_password_dock-id"),
        (hass, DOMAIN, "dock_unreachable_dock-id"),
    }


def test_resolved_dock_issue_deletes_only_its_own_entry():
    """A recovered dock does not clear another remote's issue."""
    from homeassistant.helpers import issue_registry

    hass = Mock()
    with patch.object(issue_registry, "async_delete_issue") as delete:
        async_delete_issue_dock_unreachable(hass, "entry-one", "dock-id")

    delete.assert_called_once_with(
        hass, DOMAIN, dock_unreachable_issue_id("entry-one", "dock-id")
    )


@pytest.mark.asyncio
async def test_repair_flow_routes_entry_scoped_websocket_issue():
    """The repair dispatcher accepts the entry-scoped WebSocket issue ID."""
    hass = Mock()
    entry = Mock(entry_id="entry-one")
    flow = await async_create_fix_flow(
        hass,
        websocket_connection_issue_id(entry.entry_id),
        {"config_entry": entry},
    )
    assert isinstance(flow, WebSocketRepairFlow)


@pytest.mark.asyncio
async def test_unload_preserves_issues_during_reload():
    """Issue registry ownership handles removal; unload only unloads platforms."""
    from custom_components.unfoldedcircle import PLATFORMS, async_unload_entry
    from homeassistant.helpers import issue_registry

    hass = Mock()
    hass.config_entries.async_unload_platforms_or_raise = AsyncMock()
    entry = Mock(entry_id="entry-one")
    with patch.object(issue_registry, "async_delete_issue") as delete:
        assert await async_unload_entry(hass, entry) is None

    hass.config_entries.async_unload_platforms_or_raise.assert_awaited_once_with(
        entry, PLATFORMS
    )
    delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_listener_schedules_reload():
    """Entry updates use Home Assistant's retry-safe reload scheduling."""
    hass = Mock()
    await _async_update_listener(hass, Mock(entry_id="remote-entry"))
    hass.config_entries.async_schedule_reload.assert_called_once_with("remote-entry")
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage", ["authentication", "connection", "initialization"]
)
async def test_failed_setup_registers_session_cleanup(failure_stage):
    """Sessions opened before setup fails are released by HA's unload callbacks."""
    import aiohttp
    from unfurled.helpers.exceptions import AuthenticationError

    from custom_components.unfoldedcircle import async_setup_entry
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

    callbacks = []
    entry = Mock(data={"host": "remote", "pin": "1234", "apiKey": "key"})
    entry.async_on_unload.side_effect = callbacks.append
    remote = Mock()
    session = None

    async def validate():
        nonlocal session
        session = aiohttp.ClientSession()
        if failure_stage == "authentication":
            raise AuthenticationError("Invalid API key or PIN")
        if failure_stage == "connection":
            raise ConnectionError("Connection failed")
        return True

    async def close():
        if session is not None:
            await session.close()

    remote.validate_connection = AsyncMock(side_effect=validate)
    remote.close = AsyncMock(side_effect=close)
    remote.init = AsyncMock(side_effect=RuntimeError("Initialization failed"))
    expected = {
        "authentication": ConfigEntryAuthFailed,
        "connection": ConfigEntryNotReady,
        "initialization": RuntimeError,
    }[failure_stage]
    try:
        with (
            patch("custom_components.unfoldedcircle.Remote", return_value=remote),
            patch(
                "custom_components.unfoldedcircle.UnfoldedCircleRemoteCoordinator",
                return_value=Mock(api=remote),
            ),
            pytest.raises(expected),
        ):
            await async_setup_entry(Mock(), entry)
        assert callbacks == [remote.close]
        # HA processes these callbacks even when async_setup_entry raises.
        for callback in reversed(callbacks):
            await callback()
        assert session is not None and session.closed
        remote.close.assert_awaited_once()
    finally:
        if session is not None:
            await session.close()


@pytest.mark.asyncio
async def test_validate_tokens_uses_admin_when_owner_is_missing():
    token = SimpleNamespace(client_name="UCR:Remote Two")
    admin = SimpleNamespace(
        id="admin-id",
        is_active=True,
        system_generated=False,
        is_admin=True,
        refresh_tokens={"token-id": token},
    )
    hass = Mock()
    hass.auth.async_get_owner = AsyncMock(return_value=None)
    hass.auth.async_get_users = AsyncMock(return_value=[admin])
    hass.auth.async_get_user = AsyncMock(return_value=admin)
    remote = Mock()
    remote.device.name = "Remote Two"
    remote.auth.system_has_token = AsyncMock(return_value=True)

    assert await validate_tokens(hass, remote) is True
    hass.auth.async_get_user.assert_awaited_once_with("admin-id")
    remote.auth.system_has_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_tokens_without_eligible_user_returns_false():
    hass = Mock()
    hass.auth.async_get_owner = AsyncMock(return_value=None)
    hass.auth.async_get_users = AsyncMock(return_value=[])
    remote = Mock()

    assert await validate_tokens(hass, remote) is False
    remote.auth.system_has_token.assert_not_called()
