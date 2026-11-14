"""Firmware download and installation lifecycle coverage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from unfurled.helpers.exceptions import HTTPError

from custom_components.unfoldedcircle.update import Update
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def entity():
    coordinator = Mock()
    coordinator.api.system.update_info = SimpleNamespace(
        in_progress=False,
        download_percent=0,
        download_state=None,
        update_percent=0,
        latest_version="2",
        release_notes="",
    )
    coordinator.api.device.sw_version = "1"
    coordinator.api.system.update_firmware = AsyncMock(return_value="START")
    coordinator.api.system.get_update_status = AsyncMock()
    entity = Update(coordinator)
    entity.async_write_ha_state = Mock()
    return entity


@pytest.mark.asyncio
async def test_already_downloaded(entity):
    await entity.async_install(None, False)
    entity.coordinator.api.system.update_firmware.assert_awaited_once()
    entity.coordinator.api.system.get_update_status.assert_not_awaited()
    assert entity._attr_in_progress is True


@pytest.mark.asyncio
async def test_download_then_retry_install(entity):
    system = entity.coordinator.api.system
    system.update_firmware.side_effect = [
        "DOWNLOAD",
        HTTPError(409, "Busy"),
        "DOWNLOAD",
        "START",
    ]
    system.get_update_status.side_effect = [
        {"state": "DOWNLOAD", "download_percent": percentage}
        for percentage in [10, 50, 99, 100, 100, 100]
    ]
    progress = []
    entity.async_write_ha_state.side_effect = lambda: progress.append(
        entity.update_percentage
    )
    with patch(
        "custom_components.unfoldedcircle.update.Update._async_wait_for_download_poll",
        new_callable=AsyncMock,
    ):
        await entity.async_install(None, False)
    assert system.update_firmware.await_count == 4
    assert progress == [0, 1, 5, 9, 10, 10, 10, 10]
    assert entity._attr_in_progress is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["retries", "stall", "failure", "http", "timeout"])
async def test_failure_clears_progress(entity, failure):
    system = entity.coordinator.api.system
    system.update_firmware.return_value = "DOWNLOAD"
    system.get_update_status.return_value = {
        "state": "DOWNLOAD",
        "download_percent": 100,
    }
    if failure == "stall":
        system.get_update_status.return_value["download_percent"] = 30
    elif failure == "failure":
        system.get_update_status.return_value = {"state": "FAILURE"}
    elif failure == "http":
        system.get_update_status.side_effect = HTTPError(404, "Not found")
    elif failure == "timeout":
        system.get_update_status.side_effect = TimeoutError
    with (
        patch(
            "custom_components.unfoldedcircle.update.Update._async_wait_for_download_poll",
            new_callable=AsyncMock,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await entity.async_install(None, False)
    assert entity._attr_in_progress is False
    assert entity._updated_requested is False
    assert entity._is_downloading is False
    # Late WebSocket progress cannot revive a cancelled HA attempt.
    system.update_info.download_percent = 100
    entity._handle_coordinator_update()
    assert entity._attr_in_progress is False
    assert entity.update_percentage is None


@pytest.mark.asyncio
async def test_existing_install_is_monitored_without_reposting(entity):
    system = entity.coordinator.api.system
    system.update_firmware.side_effect = HTTPError(409, "Busy")
    system.get_update_status.return_value = {"state": "RUN"}
    with patch(
        "custom_components.unfoldedcircle.update.Update._async_wait_for_download_poll",
        new_callable=AsyncMock,
    ):
        await entity.async_install(None, False)
    system.update_firmware.assert_awaited_once()


@pytest.mark.asyncio
async def test_websocket_completion_survives_stale_poll(entity):
    system = entity.coordinator.api.system
    system.update_firmware.side_effect = ["DOWNLOAD", "START"]
    system.update_info.download_percent = 100
    system.get_update_status.return_value = {
        "state": "DOWNLOAD",
        "download_percent": 99,
    }
    with patch(
        "custom_components.unfoldedcircle.update.Update._async_wait_for_download_poll",
        new_callable=AsyncMock,
    ):
        await entity.async_install(None, False)
    assert system.update_firmware.await_count == 2


@pytest.mark.asyncio
async def test_progress_resets_stall_budget(entity):
    system = entity.coordinator.api.system
    system.update_firmware.side_effect = ["DOWNLOAD", "START"]
    system.get_update_status.side_effect = [
        {"state": "DOWNLOAD", "download_percent": value}
        for value in [10, 10, 20, 20, 100]
    ]
    with (
        patch(
            "custom_components.unfoldedcircle.update.Update._async_wait_for_download_poll",
            new_callable=AsyncMock,
        ),
        patch("custom_components.unfoldedcircle.update._DOWNLOAD_STALL_TIMEOUT", 12),
    ):
        await entity.async_install(None, False)
    assert entity._attr_in_progress is True


@pytest.mark.asyncio
async def test_cancelled_attempt_clears_progress(entity):
    import asyncio

    entity.coordinator.api.system.update_firmware.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await entity.async_install(None, False)
    assert entity._attr_in_progress is False
    assert entity._updated_requested is False


def test_completed_install_clears_progress(entity):
    entity._updated_requested = True
    entity.coordinator.api.device.sw_version = "2"
    entity._handle_coordinator_update()
    assert entity._attr_in_progress is False
    assert entity._updated_requested is False


@pytest.mark.asyncio
async def test_websocket_failure_wakes_wait_and_clears_spinner(entity):
    import asyncio

    system = entity.coordinator.api.system
    system.update_firmware.return_value = "DOWNLOAD"
    task = asyncio.create_task(entity.async_install(None, False))
    await asyncio.sleep(0)
    system.update_info.download_state = "FAILURE"
    entity._handle_coordinator_update()
    assert entity._attr_in_progress is False
    # A stale poll/event must not erase the latched failure.
    system.update_info.download_state = "DOWNLOAD"
    entity._handle_coordinator_update()
    assert entity._attr_in_progress is False
    with pytest.raises(HomeAssistantError, match="download failure"):
        await asyncio.wait_for(task, timeout=1)
    system.get_update_status.assert_not_awaited()
    assert entity._is_downloading is False
    # A fresh attempt must clear the failure latch.
    system.update_info.download_state = None
    system.update_firmware.return_value = "START"
    await entity.async_install(None, False)
    assert entity._attr_in_progress is True


@pytest.mark.asyncio
async def test_poll_observes_dependency_download_failure(entity):
    system = entity.coordinator.api.system
    system.update_firmware.return_value = "DOWNLOAD"

    async def poll():
        system.update_info.download_state = "FAILURE"
        return {"state": "DOWNLOAD", "download_percent": 99}

    system.get_update_status.side_effect = poll
    with (
        patch.object(entity, "_async_wait_for_download_poll", new_callable=AsyncMock),
        pytest.raises(HomeAssistantError, match="download failure"),
    ):
        await entity.async_install(None, False)
    assert entity._attr_in_progress is False
    system.update_firmware.assert_awaited_once()
