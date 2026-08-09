"""Tests for the CoreAPI layer."""

from __future__ import annotations

from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aioresponses import aioresponses

from unfurled.api import CoreAPI
from unfurled.helpers.exceptions import AuthenticationError, HTTPError

BASE = "http://192.168.1.10/api/"
API_KEY = "test-key"


@asynccontextmanager
async def core_test_server(app: web.Application):
    """Run an aiohttp server to exercise real client request behavior."""
    server = TestServer(app)
    await server.start_server()
    try:
        yield str(server.make_url("/api/"))
    finally:
        await server.close()


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

    @pytest.mark.parametrize(
        "path", ["/system", "//example.test/path", "https://example.test/path"]
    )
    def test_rejects_paths_outside_the_configured_api(self, path: str):
        api = CoreAPI("http://host/api/")
        with pytest.raises(ValueError, match="relative"):
            api._url(path)

    def test_encodes_dynamic_path_segments(self):
        api = CoreAPI("http://host/api/")
        assert api._path_segment("demo/../other?x=1") == "demo%2F..%2Fother%3Fx%3D1"


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

    async def test_custom_client_timeout(self):
        api = CoreAPI(BASE, timeout=42)
        await api._ensure_session()
        assert api._session.timeout.total == 42
        await api.close()

    async def test_request_converts_a_numeric_timeout_and_reads_bytes(self):
        received_headers: dict[str, str] = {}

        async def export(request: web.Request) -> web.Response:
            received_headers.update(request.headers)
            return web.Response(body=b"trace-data", content_type="application/octet-stream")

        app = web.Application()
        app.router.add_get("/api/export", export)
        async with core_test_server(app) as base, CoreAPI(base, api_key=API_KEY) as local_api:
            result = await local_api.request("GET", "export", timeout=0.5, response_type="bytes")

        assert result == b"trace-data"
        assert received_headers["Authorization"] == f"Bearer {API_KEY}"


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

    async def test_get_macros_supports_search_and_pagination(self, api: CoreAPI):
        payload = [{"entity_id": "uc.main.macro-1", "name": {"en_US": "Movie Time"}}]
        url = f"{BASE}macros?limit=50&page=2&q=Movie+Time"
        with aioresponses() as m:
            m.get(url, payload=payload)
            result = await api.get_macros(limit=50, page=2, q="Movie Time")
        assert result == payload

    async def test_get_macro_encodes_entity_id(self, api: CoreAPI):
        payload = {"entity_id": "uc.main.macro/1"}
        with aioresponses() as m:
            m.get(f"{BASE}macros/uc.main.macro%2F1", payload=payload)
            result = await api.get_macro("uc.main.macro/1")
        assert result == payload

    async def test_get_pub_version(self, api: CoreAPI):
        payload = {"hostname": "remote", "address": "aa:bb:cc:dd:ee:ff", "os": "2.3.0"}
        with aioresponses() as m:
            m.get(f"{BASE}pub/version", payload=payload)
            result = await api.get_pub_version()
        assert result["hostname"] == "remote"

    async def test_version_and_device_conveniences(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(f"{BASE}pub/version", payload={"os": "2.3.0"})
            m.get(f"{BASE}cfg/device", payload={"name": "Living Room"})
            version = await api.get_version()
            name = await api.get_device_name()
        assert version["os"] == "2.3.0"
        assert name == "Living Room"

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
        payload = [{"dock_id": "uc-dock-001", "name": "My Dock"}]
        with aioresponses() as m:
            m.get(f"{BASE}docks?limit=100", payload=payload)
            result = await api.get_docks()
        assert result[0]["dock_id"] == "uc-dock-001"

    async def test_put_ir_send(self, api: CoreAPI):
        with aioresponses() as m:
            m.put(f"{BASE}ir/emitters/emitter-001/send", payload={"status": "ok"})
            result = await api.put_ir_send("emitter-001", {"code": "0x1234", "format": "HEX"})
        assert result is not None

    async def test_get_ir_manufacturer_endpoints(self):
        received: dict[str, dict[str, str]] = {}

        async def manufacturers(request: web.Request) -> web.Response:
            received["manufacturers"] = dict(request.query)
            return web.json_response([{"id": "lg", "name": "LG"}])

        async def codesets(request: web.Request) -> web.Response:
            received["codesets"] = dict(request.query)
            return web.json_response([{"id": "hfwgPmT", "name": "Generic TV 1", "custom": False}])

        async def commands(_request: web.Request) -> web.Response:
            return web.json_response(["POWER_ON", "POWER_OFF"])

        app = web.Application()
        app.router.add_get("/api/ir/codes/manufacturers", manufacturers)
        app.router.add_get("/api/ir/codes/manufacturers/lg", codesets)
        app.router.add_get("/api/ir/codes/manufacturers/lg/hfwgPmT", commands)
        async with core_test_server(app) as base, CoreAPI(base) as local_api:
            manufacturers_result = await local_api.get_ir_manufacturers(page=2, q="lg")
            codesets_result = await local_api.get_ir_manufacturer_codesets("lg", page=2, q="tv")
            commands_result = await local_api.get_ir_manufacturer_codeset_commands("lg", "hfwgPmT")

        assert received == {
            "manufacturers": {"limit": "100", "page": "2", "q": "lg"},
            "codesets": {"limit": "100", "page": "2", "q": "tv"},
        }
        assert manufacturers_result == [{"id": "lg", "name": "LG"}]
        assert codesets_result[0]["id"] == "hfwgPmT"
        assert commands_result == ["POWER_ON", "POWER_OFF"]

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

    async def test_create_api_key_can_replace_an_existing_named_key(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(f"{BASE}auth/api_keys?limit=100", payload=[{"name": "manager", "key_id": "k1"}])
            m.delete(f"{BASE}auth/api_keys/k1", status=204, body="")
            m.post(f"{BASE}auth/api_keys", payload={"api_key": "new-key"})
            result = await api.create_api_key("manager", ["admin"], replace_existing=True)
        assert result == {"api_key": "new-key"}

    async def test_get_dock_update_alias(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(f"{BASE}docks/devices/dock-1/update", payload={"available": True})
            result = await api.get_dock_update("dock-1")
        assert result == {"available": True}

    async def test_get_integration_entities_has_no_whitespace_in_query(self, api: CoreAPI):
        payload = [{"entity_id": "media_player.tv"}]
        url = f"{BASE}intg/instances/demo/entities?reload=true&limit=50&filter=NEW&page=2"
        with aioresponses() as m:
            m.get(url, payload=payload)
            result = await api.get_integration_entities(
                "demo", reload=True, limit=50, filter="NEW", page=2
            )
        assert result == payload

    async def test_get_integrations_filters_by_driver_without_unsupported_query(self, api: CoreAPI):
        url = f"{BASE}intg/instances?limit=50&enabled=true&page=2"
        payload = [{"driver_id": "demo"}, {"driver_id": "other"}]
        with aioresponses() as m:
            m.get(url, payload=payload)
            result = await api.get_integrations(50, enabled=True, driver_id="demo", page=2)
        assert result == [{"driver_id": "demo"}]

    async def test_get_drivers_supports_filters(self, api: CoreAPI):
        url = (
            f"{BASE}intg/drivers?limit=50&driver_type=CUSTOM&has_instances=false"
            "&instantiable=true&enabled=true&page=2"
        )
        with aioresponses() as m:
            m.get(url, payload=[])
            result = await api.get_drivers(
                50,
                driver_type="CUSTOM",
                has_instances=False,
                instantiable=True,
                enabled=True,
                page=2,
            )
        assert result == []

    async def test_install_archive_sends_multipart_data_and_uses_numeric_timeout(self):
        received: dict[str, object] = {}

        async def install(request: web.Request) -> web.Response:
            field = await (await request.multipart()).next()
            assert field is not None
            received["data"] = await field.read()
            received["filename"] = field.filename
            received["content_type"] = field.headers.get("Content-Type")
            received["update"] = request.query.get("update")
            return web.json_response({"driver_id": "demo"}, status=201)

        app = web.Application()
        app.router.add_post("/api/intg/install", install)
        async with core_test_server(app) as base, CoreAPI(base) as local_api:
            result = await local_api.post_integration_install(
                b"archive", "demo.tar.gz", update=True, timeout=0.5
            )

        assert result == {"driver_id": "demo"}
        assert received == {
            "data": b"archive",
            "filename": "demo.tar.gz",
            "content_type": "application/x-gzip",
            "update": "true",
        }

    async def test_entity_configuration_sends_required_bodies_and_returns_api_shape(self):
        received: dict[str, object] = {}

        async def configure_many(request: web.Request) -> web.Response:
            received["many"] = await request.json()
            return web.json_response(["media_player.tv"], status=201)

        async def configure_one(request: web.Request) -> web.Response:
            received["one"] = await request.json()
            return web.json_response({"entity_id": "media_player.tv"}, status=201)

        app = web.Application()
        app.router.add_post("/api/intg/instances/demo/entities", configure_many)
        app.router.add_post("/api/intg/instances/demo/entities/media_player.tv", configure_one)
        async with core_test_server(app) as base, CoreAPI(base) as local_api:
            all_entities = await local_api.post_integration_entities("demo")
            entity = await local_api.post_integration_entity(
                "demo", "media_player.tv", {"name": "TV"}
            )

        assert all_entities == ["media_player.tv"]
        assert entity == {"entity_id": "media_player.tv"}
        assert received == {"many": [], "one": {"name": "TV"}}

    async def test_setup_lifecycle_endpoints(self, api: CoreAPI):
        with aioresponses() as m:
            m.get(f"{BASE}intg/setup/demo", payload={"state": "WAIT_USER_ACTION"})
            m.delete(f"{BASE}intg/setup/demo", status=204, body="")
            setup = await api.get_integration_setup("demo")
            await api.delete_integration_setup("demo")
        assert setup["state"] == "WAIT_USER_ACTION"

    async def test_setup_confirmation_and_validation(self, api: CoreAPI):
        with aioresponses() as m:
            m.put(f"{BASE}intg/setup/demo", payload={"state": "SETUP"})
            result = await api.put_integration_setup("demo", confirm=True)
        assert result == {"state": "SETUP"}
        with pytest.raises(ValueError, match="exactly one"):
            await api.put_integration_setup("demo")
        with pytest.raises(ValueError, match="exactly one"):
            await api.put_integration_setup("demo", {"host": "x"}, confirm=True)

    async def test_log_export_returns_text(self, api: CoreAPI):
        url = f"{BASE}system/logs?limit=50&p=6&s=custom-intg-demo"
        with aioresponses() as m:
            m.get(url, body="2026-01-01 demo log")
            result = await api.get_logs(
                priority=6, service="custom-intg-demo", limit=50, as_text=True, timeout=30
            )
        assert result == "2026-01-01 demo log"

    @pytest.mark.parametrize("kwargs", [{"limit": -1}, {"limit": 10_001}, {"priority": 9}])
    async def test_log_query_validates_api_bounds(self, api: CoreAPI, kwargs: dict):
        with pytest.raises(ValueError):
            await api.get_logs(**kwargs)

    async def test_ir_collections_support_pagination_and_kind_filters(self):
        received: dict[str, dict[str, str]] = {}

        async def remotes(request: web.Request) -> web.Response:
            received["remotes"] = dict(request.query)
            return web.json_response([])

        async def custom_codes(request: web.Request) -> web.Response:
            received["codes"] = dict(request.query)
            return web.json_response([])

        app = web.Application()
        app.router.add_get("/api/remotes", remotes)
        app.router.add_get("/api/ir/codes/custom", custom_codes)
        async with core_test_server(app) as base, CoreAPI(base) as local_api:
            await local_api.get_remotes(limit=25, kind="IR", page=2)
            await local_api.get_ir_custom_codes(limit=25, page=3)

        assert received == {
            "remotes": {"limit": "25", "kind": "IR", "page": "2"},
            "codes": {"limit": "25", "page": "3"},
        }


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
        async with aiohttp.ClientSession() as ext_session:
            api = CoreAPI(BASE, api_key=API_KEY, session=ext_session)
            await api.close()
            # External session should still be open
            assert not ext_session.closed

    async def test_replacement_session_is_closed_after_external_session_closes(self):
        external_session = aiohttp.ClientSession()
        api = CoreAPI(BASE, session=external_session)
        await external_session.close()

        replacement = await api._ensure_session()
        assert replacement is not external_session
        await api.close()
        assert api._session is None
