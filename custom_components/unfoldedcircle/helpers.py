"""Helper functions for Unfolded Circle Devices"""

import asyncio
import logging
from pyUnfoldedCircleRemote.dock_websocket import DockWebsocket
from pyUnfoldedCircleRemote.remote import Remote

_LOGGER = logging.getLogger(__name__)


async def validate_dock_password(remote_api: Remote, user_info) -> bool:
    """Validate"""
    dock = remote_api.get_dock_by_id(user_info.get("id"))

    websocket = DockWebsocket(
        dock._ws_endpoint,
        api_key=dock.apikey,
        dock_password=user_info.get("password"),
    )
    try:
        return await asyncio.create_task(websocket.is_password_valid())
    except Exception as ex:
        _LOGGER.error("Error occurred when validating dock: %s %s", dock.name, ex)
