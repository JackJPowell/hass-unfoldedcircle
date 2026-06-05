"""Agnostic REST API layer for the Unfolded Circle Core API.

``CoreAPI`` is a thin, stateless HTTP client that maps 1-to-1 with the
remote's REST endpoints.  It returns raw ``dict`` / ``list`` payloads and
raises ``HTTPError`` on non-2xx responses.  All business logic, state
management, and domain modelling live in the higher-level classes that
consume this layer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .helpers.exceptions import AuthenticationError, HTTPError

_LOGGER = logging.getLogger(__name__)

_AUTH_USERNAME = "web-configurator"
_DEFAULT_TIMEOUT = 5.0


class IntegrationInstanceCommand(StrEnum):
    """Commands that can be sent to an integration driver instance."""

    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"


class CoreAPI:
    """Stateless HTTP client for the Unfolded Circle Core REST API.

    Typical usage::

        async with CoreAPI("http://192.168.1.10/api/", api_key="abc") as api:
            info = await api.get_system_info()

    The instance can also be used without a context manager - call
    :meth:`close` explicitly when finished.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        pin: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        self._api_key = api_key
        self._pin = pin
        self._timeout = timeout
        self._external_session = session
        self._session: aiohttp.ClientSession | None = session

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CoreAPI:
        await self._ensure_session()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the managed session (no-op if the session was supplied externally)."""
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None

    def __del__(self) -> None:
        """Best-effort cleanup when the session is GC'd without being explicitly closed.

        If the event loop is still running (e.g. GC triggered mid-coroutine),
        the close is scheduled as a task.  Otherwise a temporary loop is created
        just to drain the session.
        """
        if self._external_session or not self._session or self._session.closed:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.close())
        except RuntimeError:
            with contextlib.suppress(Exception):
                asyncio.run(self.close())
        except Exception:
            pass

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = self._make_session()
        return self._session

    def _make_session(self) -> aiohttp.ClientSession:
        headers: dict[str, str] = {"Accept": "application/json"}
        auth: aiohttp.BasicAuth | None = None

        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        elif self._pin:
            auth = aiohttp.BasicAuth(_AUTH_USERNAME, self._pin)

        return aiohttp.ClientSession(
            headers=headers,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=self._timeout),
        )

    # ------------------------------------------------------------------
    # Low-level request helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build an absolute URL from a relative *path*."""
        return urljoin(self._base_url, path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
    ) -> Any:
        session = await self._ensure_session()
        url = self._url(path)
        _LOGGER.debug("CoreAPI %s %s", method.upper(), url)
        async with session.request(method, url, json=json, params=params) as response:
            await self._raise_on_error(response)
            if response.content_length == 0 or response.status == 204:
                return None
            return await response.json()

    @staticmethod
    async def _raise_on_error(response: aiohttp.ClientResponse) -> None:
        if response.ok:
            return
        if response.status == 401:
            raise AuthenticationError("Authentication failed (check API key / PIN)")
        try:
            body = await response.json()
            msg = f"{body.get('code', '')} - {body.get('message', response.reason)}"
        except Exception:
            msg = response.reason or "Unknown error"
        raise HTTPError(response.status, msg)

    async def _get(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def _put(self, path: str, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def _patch(self, path: str, json: Any = None) -> Any:
        return await self._request("PATCH", path, json=json)

    async def _delete(self, path: str, json: Any = None) -> Any:
        return await self._request("DELETE", path, json=json)

    async def _get_paginated(self, path: str, limit: int = 100) -> list[dict]:
        """Fetch all pages of a paginated endpoint."""
        results: list[dict] = []
        page = 1
        while True:
            session = await self._ensure_session()
            url = self._url(path)
            params = {"limit": limit, "page": page}
            async with session.get(url, params=params) as response:
                await self._raise_on_error(response)
                count = int(response.headers.get("pagination-count", 0))
                data: list[dict] = await response.json()
                results.extend(data)
                if len(results) >= count or not data:
                    break
                page += 1
        return results

    # ------------------------------------------------------------------
    # Unauthenticated / public endpoints
    # ------------------------------------------------------------------

    async def get_pub_version(self) -> dict:
        """GET /pub/version - firmware version without authentication."""
        return await self._get("pub/version")

    async def get_pub_status(self) -> dict:
        """GET /pub/status - system resource usage."""
        return await self._get("pub/status")

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    async def get_system_info(self) -> dict:
        """GET /system"""
        return await self._get("system")

    async def get_wifi_info(self) -> dict:
        """GET /system/wifi"""
        return await self._get("system/wifi")

    async def get_configuration(self) -> dict:
        """GET /cfg - full device configuration."""
        return await self._get("cfg")

    async def post_system_command(self, cmd: str) -> None:
        """POST /system?cmd=<cmd>"""
        await self._post(f"system?cmd={cmd}")

    # ------------------------------------------------------------------
    # Power / battery
    # ------------------------------------------------------------------

    async def get_battery(self) -> dict:
        """GET /system/power/battery"""
        return await self._get("system/power/battery")

    async def get_power(self) -> dict:
        """GET /system/power"""
        return await self._get("system/power")

    async def get_charger(self) -> dict:
        """GET /system/power/charger"""
        return await self._get("system/power/charger")

    async def put_wireless_charging(self, enabled: bool) -> dict:
        """PUT /system/power/charger  - enable / disable wireless charging."""
        return await self._put("system/power/charger", json={"wireless_charging_enabled": enabled})

    async def get_ambient_light(self) -> dict:
        """GET /system/sensors/ambient_light"""
        return await self._get("system/sensors/ambient_light")

    # ------------------------------------------------------------------
    # Standby inhibitors
    # ------------------------------------------------------------------

    async def get_standby_inhibitors(self) -> list[dict]:
        """GET /system/power/standby_inhibitors"""
        return await self._get("system/power/standby_inhibitors")

    async def post_standby_inhibitor(self, body: dict) -> dict:
        """POST /system/power/standby_inhibitors"""
        return await self._post("system/power/standby_inhibitors", json=body)

    async def delete_standby_inhibitor(self, inhibitor_id: str) -> None:
        """DELETE /system/power/standby_inhibitors/{id}"""
        await self._delete(f"system/power/standby_inhibitors/{inhibitor_id}")

    async def delete_all_standby_inhibitors(self) -> None:
        """DELETE /system/power/standby_inhibitors"""
        await self._delete("system/power/standby_inhibitors")

    # ------------------------------------------------------------------
    # Settings / configuration
    # ------------------------------------------------------------------

    async def get_display_settings(self) -> dict:
        """GET /cfg/display - retrieve current display configuration."""
        return await self._get("cfg/display")

    async def patch_device_settings(self, settings: dict) -> dict:
        """PATCH /cfg/device - update the device name."""
        return await self._patch("cfg/device", json=settings)

    async def patch_display_settings(self, settings: dict) -> dict:
        """PATCH /cfg/display"""
        return await self._patch("cfg/display", json=settings)

    async def get_button_settings(self) -> dict:
        """GET /cfg/button - retrieve current button backlight configuration."""
        return await self._get("cfg/button")

    async def patch_button_settings(self, settings: dict) -> dict:
        """PATCH /cfg/button"""
        return await self._patch("cfg/button", json=settings)

    async def get_sound_settings(self) -> dict:
        """GET /cfg/sound - retrieve current sound effect configuration."""
        return await self._get("cfg/sound")

    async def patch_sound_settings(self, settings: dict) -> dict:
        """PATCH /cfg/sound"""
        return await self._patch("cfg/sound", json=settings)

    async def get_haptic_settings(self) -> dict:
        """GET /cfg/haptic - retrieve current haptic feedback configuration."""
        return await self._get("cfg/haptic")

    async def patch_haptic_settings(self, settings: dict) -> dict:
        """PATCH /cfg/haptic"""
        return await self._patch("cfg/haptic", json=settings)

    async def get_power_saving_settings(self) -> dict:
        """GET /cfg/power_saving - retrieve current power-saving configuration."""
        return await self._get("cfg/power_saving")

    async def patch_power_saving_settings(self, settings: dict) -> dict:
        """PATCH /cfg/power_saving"""
        return await self._patch("cfg/power_saving", json=settings)

    async def get_network_settings(self) -> dict:
        """GET /cfg/network - retrieve Wi-Fi and Bluetooth network configuration."""
        return await self._get("cfg/network")

    async def patch_network_settings(self, settings: dict) -> dict:
        """PATCH /cfg/network"""
        return await self._patch("cfg/network", json=settings)

    async def get_localization_settings(self) -> dict:
        """GET /cfg/localization - retrieve language and region settings."""
        return await self._get("cfg/localization")

    async def patch_localization_settings(self, settings: dict) -> dict:
        """PATCH /cfg/localization"""
        return await self._patch("cfg/localization", json=settings)

    async def get_update_settings(self) -> dict:
        """GET /cfg/software_update - retrieve software update configuration."""
        return await self._get("cfg/software_update")

    async def patch_software_update_settings(self, settings: dict) -> dict:
        """PATCH /cfg/software_update"""
        return await self._patch("cfg/software_update", json=settings)

    # ------------------------------------------------------------------
    # Software updates
    # ------------------------------------------------------------------

    async def get_system_update(self) -> dict:
        """GET /system/update"""
        return await self._get("system/update")

    async def put_system_update(self) -> dict:
        """PUT /system/update - force an update check."""
        return await self._put("system/update")

    async def get_system_update_latest(self) -> dict:
        """GET /system/update/latest"""
        return await self._get("system/update/latest")

    async def post_system_update_latest(self, body: dict | None = None) -> dict:
        """POST /system/update/latest - install latest firmware."""
        return await self._post("system/update/latest", json=body)

    # ------------------------------------------------------------------
    # Activities
    # ------------------------------------------------------------------

    async def get_activities(self, limit: int = 100) -> list[dict]:
        """GET /activities?limit=<n>"""
        return await self._get(f"activities?limit={limit}")

    async def get_activity(self, activity_id: str) -> dict:
        """GET /activities/{id}"""
        return await self._get(f"activities/{activity_id}")

    async def patch_activity(self, activity_id: str, body: dict) -> dict:
        """PATCH /activities/{id}"""
        return await self._patch(f"activities/{activity_id}", json=body)

    async def get_activity_buttons(self, activity_id: str) -> list[dict]:
        """GET /activities/{id}/buttons"""
        return await self._get(f"activities/{activity_id}/buttons")

    async def get_activity_button(self, activity_id: str, button_id: str) -> dict:
        """GET /activities/{id}/buttons/{button_id}"""
        return await self._get(f"activities/{activity_id}/buttons/{button_id}")

    async def get_activity_groups(self, limit: int = 100) -> list[dict]:
        """GET /activity_groups?limit=<n>"""
        return await self._get(f"activity_groups?limit={limit}")

    async def get_activity_group(self, group_id: str) -> dict:
        """GET /activity_groups/{id}"""
        return await self._get(f"activity_groups/{group_id}")

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------

    async def put_entity_command(
        self, entity_id: str, cmd_id: str, params: dict | None = None
    ) -> dict:
        """PUT /entities/{id}/command"""
        body: dict = {"entity_id": entity_id, "cmd_id": cmd_id}
        if params:
            body["params"] = params
        return await self._put(f"entities/{entity_id}/command", json=body)

    async def get_entity(self, entity_id: str) -> dict:
        """GET /entities/{id}"""
        return await self._get(f"entities/{entity_id}")

    async def delete_entity(self, entity_id: str) -> None:
        """DELETE /entities/{id}"""
        await self._delete(f"entities/{entity_id}")

    async def delete_entities(self, entity_ids: list[str]) -> None:
        """DELETE /entities  with a JSON body of entity IDs."""
        await self._delete("entities", json={"entity_ids": entity_ids})

    # ------------------------------------------------------------------
    # IR / remotes / codesets
    # ------------------------------------------------------------------

    async def get_ir_emitters(self, limit: int = 100) -> list[dict]:
        """GET /ir/emitters?limit=<n>"""
        return await self._get(f"ir/emitters?limit={limit}")

    async def put_ir_send(self, emitter_id: str, body: dict) -> dict:
        """PUT /ir/emitters/{id}/send"""
        return await self._put(f"ir/emitters/{emitter_id}/send", json=body)

    async def get_ir_custom_codes(self, limit: int = 100) -> list[dict]:
        """GET /ir/codes/custom?limit=<n>"""
        return await self._get(f"ir/codes/custom?limit={limit}")

    async def get_ir_manufacturers(self, query: str, page: int = 1, limit: int = 100) -> dict:
        """GET /ir/codes/manufacturers"""
        return await self._get(f"ir/codes/manufacturers?page={page}&limit={limit}&q={query}")

    async def get_ir_manufacturer_codesets(
        self, manufacturer_id: str, page: int = 1, limit: int = 100
    ) -> dict:
        """GET /ir/codes/manufacturers/{id}"""
        return await self._get(
            f"ir/codes/manufacturers/{manufacturer_id}?page={page}&limit={limit}"
        )

    async def get_remotes(self, limit: int = 100) -> list[dict]:
        """GET /remotes - IR remote devices (not the physical UC remote)."""
        return await self._get(f"remotes?limit={limit}")

    async def get_remote_ir_codesets(self, remote_id: str) -> list[dict]:
        """GET /remotes/{id}/ir"""
        return await self._get(f"remotes/{remote_id}/ir")

    # ------------------------------------------------------------------
    # Docks
    # ------------------------------------------------------------------

    async def get_docks(self, limit: int = 100) -> list[dict]:
        """GET /docks"""
        return await self._get(f"docks?limit={limit}")

    async def get_dock(self, dock_id: str) -> dict:
        """GET /docks/{id}"""
        return await self._get(f"docks/{dock_id}")

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    async def get_api_keys(self) -> list[dict]:
        """GET /auth/api_keys"""
        return await self._get("auth/api_keys?limit=100")

    async def post_api_key(self, name: str, scopes: list[str]) -> dict:
        """POST /auth/api_keys"""
        return await self._post("auth/api_keys", json={"name": name, "scopes": scopes})

    async def delete_api_key(self, key_id: str) -> None:
        """DELETE /auth/api_keys/{id}"""
        await self._delete(f"auth/api_keys/{key_id}")

    # ------------------------------------------------------------------
    # Integrations / drivers
    # ------------------------------------------------------------------

    async def get_integrations(self, limit: int = 100) -> list[dict]:
        """GET /intg/instances  (all pages)."""
        return await self._get(f"intg/instances?limit={limit}")

    async def get_integration(self, integration_id: str) -> dict:
        """GET /intg/instances/{id}"""
        return await self._get(f"intg/instances/{integration_id}")

    async def put_integration(
        self, integration_id: str, cmd: IntegrationInstanceCommand | None = None
    ) -> dict:
        """PUT /intg/instances/{id}  (optionally with ?cmd=<cmd>)."""
        path = f"intg/instances/{integration_id}"
        if cmd:
            path += f"?cmd={cmd}"
        return await self._put(path)

    async def get_integration_entities(
        self, integration_id: str, reload: bool = False, limit: int = 100
    ) -> list[dict]:
        """GET /intg/instances/{id}/entities"""
        return await self._get(
            f"intg/instances/{integration_id}/entities?reload= \
                {'true' if reload else 'false'}&limit={limit}"
        )

    async def post_integration_entities(self, integration_id: str, entity_ids: list[str]) -> dict:
        """POST /intg/instances/{id}/entities"""
        return await self._post(f"intg/instances/{integration_id}/entities", json=entity_ids)

    async def get_drivers(self, limit: int = 100) -> list[dict]:
        """GET /intg/drivers"""
        return await self._get(f"intg/drivers?limit={limit}")

    async def get_driver(self, driver_id: str) -> dict:
        """GET /intg/drivers/{id}"""
        return await self._get(f"intg/drivers/{driver_id}")

    async def post_driver(self, driver_id: str, body: dict) -> dict:
        """POST /intg/drivers/{id}"""
        return await self._post(f"intg/drivers/{driver_id}", json=body)

    async def start_driver(self, driver_id: str) -> dict:
        """PUT /intg/drivers/{id}?cmd=START"""
        return await self._put(f"intg/drivers/{driver_id}?cmd=START")

    async def post_integration_setup(self, body: dict) -> dict:
        """POST /intg/setup"""
        return await self._post("intg/setup", json=body)

    async def put_integration_setup(self, driver_id: str, input_values: dict) -> dict:
        """PUT /intg/setup/{driver_id}"""
        return await self._put(f"intg/setup/{driver_id}", json={"input_values": input_values})

    # ------------------------------------------------------------------
    # External systems / tokens
    # ------------------------------------------------------------------

    async def get_external_systems(self) -> list[dict]:
        """GET /auth/external"""
        return await self._get("auth/external")

    async def get_external_system(self, system: str) -> list[dict]:
        """GET /auth/external/{system}"""
        return await self._get(f"auth/external/{system}")

    async def post_external_system_token(self, system: str, body: dict) -> dict:
        """POST /auth/external/{system}"""
        return await self._post(f"auth/external/{system}", json=body)

    async def put_external_system_token(self, system: str, token_id: str, body: dict) -> dict:
        """PUT /auth/external/{system}/{token_id}"""
        return await self._put(f"auth/external/{system}/{token_id}", json=body)

    async def delete_external_system_token(self, system: str, token_id: str) -> None:
        """DELETE /auth/external/{system}/{token_id}"""
        await self._delete(f"auth/external/{system}/{token_id}")

    # ------------------------------------------------------------------
    # Entities (filtered by integration)
    # ------------------------------------------------------------------

    async def get_subscribed_entities(self, integration_id: str) -> list[dict]:
        """GET /entities?intg_ids={integration_id} - entities subscribed to an integration."""
        return await self._get(f"entities?intg_ids={integration_id}")

    # ------------------------------------------------------------------
    # IR - remotes / codesets (write operations)
    # ------------------------------------------------------------------

    async def post_remote(self, body: dict) -> dict:
        """POST /remotes - create a new IR remote definition."""
        return await self._post("remotes", json=body)

    async def get_remote(self, remote_id: str) -> dict:
        """GET /remotes/{id} - retrieve a single IR remote definition."""
        return await self._get(f"remotes/{remote_id}")

    async def delete_ir_custom_code(self, codeset_device_id: str) -> None:
        """DELETE /ir/codes/custom/{id}"""
        await self._delete(f"ir/codes/custom/{codeset_device_id}")

    async def post_remote_ir_command(
        self, remote_entity_id: str, command_id: str, body: dict
    ) -> dict:
        """POST /remotes/{id}/ir/{command_id} - add a command to an IR remote codeset."""
        return await self._post(f"remotes/{remote_entity_id}/ir/{command_id}", json=body)

    async def patch_remote_ir_command(
        self, remote_entity_id: str, command_id: str, body: dict
    ) -> dict:
        """PATCH /remotes/{id}/ir/{command_id} - update a command in an IR remote codeset."""
        return await self._patch(f"remotes/{remote_entity_id}/ir/{command_id}", json=body)

    async def put_ir_emitter_learn(self, emitter_id: str) -> dict:
        """PUT /ir/emitters/{id}/learn - start an IR learning session."""
        return await self._put(f"ir/emitters/{emitter_id}/learn")

    async def delete_ir_emitter_learn(self, emitter_id: str) -> None:
        """DELETE /ir/emitters/{id}/learn - stop an IR learning session."""
        await self._delete(f"ir/emitters/{emitter_id}/learn")

    # ------------------------------------------------------------------
    # Dock proxy endpoints (routed through the remote's REST API)
    # ------------------------------------------------------------------

    async def get_dock_detail(self, dock_id: str) -> dict:
        """GET /docks/devices/{id} - detailed dock device info."""
        return await self._get(f"docks/devices/{dock_id}")

    async def get_dock_update_status(self, dock_id: str) -> dict:
        """GET /docks/devices/{id}/update - dock firmware update status."""
        return await self._get(f"docks/devices/{dock_id}/update")

    async def post_dock_update(self, dock_id: str) -> dict:
        """POST /docks/devices/{id}/update - trigger a dock firmware update."""
        return await self._post(f"docks/devices/{dock_id}/update")

    async def post_dock_command(self, dock_id: str, body: dict) -> dict:
        """POST /docks/devices/{id}/command - send a control command to the dock."""
        return await self._post(f"docks/devices/{dock_id}/command", json=body)
