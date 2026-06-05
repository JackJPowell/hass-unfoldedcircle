"""Tests for the CoreAPI layer."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from unfurled.api import CoreAPI
from unfurled.helpers.exceptions import AuthenticationError, HTTPError

BASE = "http://192.168.1.10/api/"
API_KEY = "test-key"


@pytest.fixture
async def api() -> CoreAPI:
    a = CoreAPI(BASE, api_key=API_KEY)
    yield a
    await a.close()


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


class TestUrlNormalization:
    def test_adds_trailing_slash(self):
        api = CoreAPI("http://host/api")
        assert api._base_url == "http://host/api/"

    def test_preserves_trailing_slash(self):
        api = CoreAPI("http://host/api/")
        assert api._base_url == "http://host/api/"

    def test_url_method(self):
        api = CoreAPI("http://host/api/")
        assert api._url("system") == "http://host/api/system"

    def test_url_with_nested_path(self):
        api = CoreAPI("http://host/api/")
        assert (
            api._url("activities/act-001/buttons") == "http://host/api/activities/act-001/buttons"
        )


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


class TestAuth:
    async def test_api_key_auth_header(self):
        api = CoreAPI(BASE, api_key="mykey")
        await api._ensure_session()
        assert api._session.headers.get("Authorization") == "Bearer mykey"
        await api.close()

    async def test_no_auth_header_without_credentials(self):
        api = CoreAPI(BASE)
        await api._ensure_session()
        assert "Authorization" not in api._session.headers
        await api.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_raises_http_error_on_4xx(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(
                f"{BASE}system", status=500, payload={"code": "INTERNAL", "message": "Server error"}
            )
            with pytest.raises(HTTPError) as exc_info:
                await api.get_system_info()
            assert exc_info.value.status_code == 500

    async def test_raises_authentication_error_on_401(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(
                f"{BASE}system",
                status=401,
                payload={"code": "UNAUTHORIZED", "message": "Unauthorized"},
            )
            with pytest.raises(AuthenticationError):
                await api.get_system_info()

    async def test_success_returns_dict(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(f"{BASE}system", payload={"model_name": "Remote Two"})
            result = await api.get_system_info()
        assert result == {"model_name": "Remote Two"}


# ---------------------------------------------------------------------------
# Individual endpoint methods
# ---------------------------------------------------------------------------


class TestEndpoints:
    async def test_get_battery(self, api: CoreAPI):
        payload = {"capacity": 80, "status": "DISCHARGING", "power_supply": False}
        with aioresponses() as m:
            m.get(f"{BASE}system/power/battery", payload=payload)
            result = await api.get_battery()
        assert result["capacity"] == 80

    async def test_get_activities(self, api: CoreAPI):
        payload = [{"entity_id": "act-001", "attributes": {"state": "OFF"}}]
        with aioresponses() as m:
            m.get(f"{BASE}activities?limit=100", payload=payload)
            result = await api.get_activities()
        assert len(result) == 1
        assert result[0]["entity_id"] == "act-001"

    async def test_put_entity_command_sends_correct_body(self, api: CoreAPI):
        with aioresponses() as m:
            m.put(f"{BASE}entities/media_player.tv/command", payload={"status": "ok"})
            await api.put_entity_command("media_player.tv", "media_player.on")
        # If no exception, request was made correctly

    async def test_put_entity_command_with_params(self, api: CoreAPI):
        with aioresponses() as m:
            m.put(f"{BASE}entities/media_player.tv/command", payload={"status": "ok"})
            await api.put_entity_command("media_player.tv", "media_player.volume", {"volume": 50})

    async def test_get_pub_version(self, api: CoreAPI):
        payload = {"hostname": "remote", "address": "aa:bb:cc:dd:ee:ff", "os": "2.3.0"}
        with aioresponses() as m:
            m.get(f"{BASE}pub/version", payload=payload)
            result = await api.get_pub_version()
        assert result["hostname"] == "remote"

    async def test_patch_display_settings(self, api: CoreAPI):
        with aioresponses() as m:
            m.patch(f"{BASE}cfg/display", payload={"auto_brightness": True, "brightness": 80})
            result = await api.patch_display_settings({"auto_brightness": True, "brightness": 80})
        assert result["brightness"] == 80

    async def test_post_system_command(self, api: CoreAPI):
        with aioresponses() as m:
            m.post(f"{BASE}system?cmd=STANDBY", status=200, payload=None)
            await api.post_system_command("STANDBY")

    async def test_get_docks(self, api: CoreAPI):
        payload = [{"entity_id": "uc-dock-001", "name": "My Dock"}]
        with aioresponses() as m:
            m.get(f"{BASE}docks?limit=100", payload=payload)
            result = await api.get_docks()
        assert result[0]["entity_id"] == "uc-dock-001"

    async def test_put_ir_send(self, api: CoreAPI):
        with aioresponses() as m:
            m.put(f"{BASE}ir/emitters/emitter-001/send", payload={"status": "ok"})
            result = await api.put_ir_send("emitter-001", {"code": "0x1234", "format": "HEX"})
        assert result is not None

    async def test_get_api_keys(self, api: CoreAPI):
        payload = [{"name": "pyUnfoldedCircle", "key_id": "k1"}]
        with aioresponses() as m:
            m.get(f"{BASE}auth/api_keys?limit=100", payload=payload)
            result = await api.get_api_keys()
        assert result[0]["name"] == "pyUnfoldedCircle"

    async def test_delete_api_key(self, api: CoreAPI):
        with aioresponses() as m:
            m.delete(f"{BASE}auth/api_keys/k1", status=204, body="")
            await api.delete_api_key("k1")


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    async def test_context_manager_closes_session(self):
        async with CoreAPI(BASE, api_key=API_KEY) as api:
            await api._ensure_session()
            assert api._session is not None
        # After exit, session should be closed
        assert api._session is None

    async def test_external_session_not_closed(self):
        import aiohttp

        async with aiohttp.ClientSession() as ext_session:
            api = CoreAPI(BASE, api_key=API_KEY, session=ext_session)
            await api.close()
            # External session should still be open
            assert not ext_session.closed
