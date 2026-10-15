"""World-side mission-control client and API tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest import mock

import httpx
from starlette.testclient import TestClient

from server.app import create_app
from server.config import load_config
from server.mc_client import McClient
from server.mc_api import build_command_context
from tests.common import REPO_ROOT


class _FakeConfig:
    def __init__(self) -> None:
        self.mc_endpoint = "127.0.0.1:8001"
        self.mc_token = "shared"
        self.mc_name = "test-world"
        self.mc_insecure_tls = True
        self.mc_ca_file = None
        self.host = "127.0.0.1"
        self.port = 5000
        self.base_path = "/world"
        self.mc_instance_id = None
        self.client_url = None
        self.entry_url = None


class _FakeWorld:
    id = "tutorial"
    label = "The Little House"
    entry_room_id = "entry"


class _FakeConnections:
    def list_all(self) -> list[object]:
        return []


class _FakeRuntime:
    def __init__(self) -> None:
        self.config = _FakeConfig()
        self.world = _FakeWorld()
        self.connections = _FakeConnections()
        self.started_at = time.time()


def _client_with(handler) -> McClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return McClient(_FakeRuntime(), client=http)


class McClientTests(unittest.TestCase):
    def test_stable_identity_and_entry_metadata_survive_mc_restart(self) -> None:
        runtime = _FakeRuntime()
        runtime.config.mc_instance_id = "mc-stable"
        runtime.config.client_url = "https://tiny.example:5100"
        runtime.config.entry_url = "https://tiny.example"
        payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            payloads.append(json.loads(request.content))
            if request.url.path.endswith("/register"):
                return httpx.Response(200, json={"instance_id": "mc-stable"})
            return httpx.Response(200, json={"ok": False, "code": "unknown_instance"})

        client = McClient(runtime, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        self.assertEqual(client.instance_id, "mc-stable")
        asyncio.run(client.register())
        asyncio.run(client.heartbeat())
        self.assertIsNone(client.instance_id)
        asyncio.run(client.register())
        self.assertEqual(payloads[0]["instance_id"], "mc-stable")
        self.assertEqual(payloads[2]["instance_id"], "mc-stable")
        self.assertEqual(payloads[2]["client_url"], "https://tiny.example:5100")
        self.assertEqual(payloads[2]["entry_room_id"], "entry")

    def test_register_and_heartbeat(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path.endswith("/register"):
                payload = json.loads(request.content)
                assert payload["instance_name"] == "test-world"
                assert payload["base_path"] == "/world"
                return httpx.Response(200, json={"ok": True, "instance_id": "mc-1", "heartbeat_seconds": 7, "capabilities": []})
            return httpx.Response(200, json={"ok": True, "pending_commands": []})

        client = _client_with(handler)
        asyncio.run(client.register())
        self.assertEqual(client.instance_id, "mc-1")
        self.assertEqual(client._heartbeat_seconds, 7)  # noqa: SLF001
        result = asyncio.run(client.heartbeat())
        self.assertEqual(result["ok"], True)
        self.assertIn("/api/mc/register", seen)
        self.assertIn("/api/mc/heartbeat", seen)

    def test_register_backoff_is_bounded(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        client = _client_with(handler)
        with mock.patch("server.mc_client.MAX_REGISTER_ATTEMPTS", 1):
            registered = asyncio.run(client.register_with_backoff())
        self.assertFalse(registered)

    def test_unknown_instance_clears_registration(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/register"):
                return httpx.Response(200, json={"ok": True, "instance_id": "mc-1", "heartbeat_seconds": 5})
            return httpx.Response(200, json={"ok": False, "code": "unknown_instance"})

        client = _client_with(handler)
        asyncio.run(client.register())
        self.assertEqual(client.instance_id, "mc-1")
        asyncio.run(client.heartbeat())
        self.assertIsNone(client.instance_id)


class WorldMcApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        env = {
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open",
            "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
            "TRSERVER_WORLDSTATE_PATH": str(root / "worldstate.sqlite3"),
            "TRSERVER_USERS_PATH": str(root / "users"),
            "TRSERVER_FEATURES": "dev_sample_activity",
            "TRSERVER_MODS": "infinite-bedrooms",
            "TRSERVER_ADMINS": "mcadmin",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": "5000",
            "TRSERVER_MC_ENDPOINT": "127.0.0.1:8001",
            "TRSERVER_MC_TOKEN": "shared",
            "TRSERVER_MC_INSECURE_TLS": "1",
        }
        self.config = load_config(env=env, repo_root=REPO_ROOT)
        self.app = create_app(self.config)
        self.client_context = TestClient(self.app, base_url="https://127.0.0.1:5000")
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        self.headers = {"X-MC-Token": "shared"}

    def _create_admin(self):
        runtime = self.client.app.state.runtime
        account = runtime.profiles.create_account("mcadmin", "password123!", runtime.world.id, runtime.world.entry_room_id)
        return runtime, account

    def test_token_required(self) -> None:
        self.assertEqual(self.client.get("/api/mc/stats").status_code, 403)
        self.assertEqual(self.client.get("/api/mc/stats", headers={"X-MC-Token": "wrong"}).status_code, 403)

    def test_stats(self) -> None:
        response = self.client.get("/api/mc/stats", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["world"]["id"], "tutorial")
        self.assertIn("schema", payload)
        self.assertIn("counters", payload)

    def test_command_requires_existing_configured_admin(self) -> None:
        runtime = self.client.app.state.runtime
        runtime.profiles.create_account("ordinary", "password123!", runtime.world.id, runtime.world.entry_room_id)
        response = self.client.post(
            "/api/mc/command",
            headers=self.headers,
            json={"command": "\\status", "actor": "ordinary"},
        )
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["code"], "admin_unavailable")
        self.assertIn("TRSERVER_ADMINS", response.json()["message"])

    def test_command_dispatch(self) -> None:
        self._create_admin()
        response = self.client.post(
            "/api/mc/command",
            headers=self.headers,
            json={"command": "\\status"},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["message"], "Server status loaded.")

    def test_command_selects_sorted_existing_admin_ignoring_legacy_actor(self) -> None:
        runtime, account = self._create_admin()
        other = runtime.profiles.create_account("zadmin", "password123!", runtime.world.id, runtime.world.entry_room_id)
        config = replace(runtime.config, bootstrap_admins=frozenset({"aaa-missing", "zadmin", "mcadmin"}))
        with mock.patch.object(runtime, "config", config):
            with mock.patch("server.mc_api.build_command_context", wraps=build_command_context) as context:
                response = self.client.post("/api/mc/command", headers=self.headers,
                                            json={"command": "\\status", "actor": other.id})
            self.assertTrue(response.json()["ok"], response.text)
            self.assertEqual(context.call_args.kwargs["account"].id, account.id)

    def test_resync_bumps_revision(self) -> None:
        response = self.client.post("/api/mc/resync", headers=self.headers, json={"scope": "all"})
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["refreshed"], 1)

    def test_restart_and_shutdown_schedule(self) -> None:
        with mock.patch("server.mc_api._schedule_restart") as restart, mock.patch("server.mc_api._schedule_exit") as stop:
            self.client.post("/api/mc/restart", headers=self.headers, json={})
            self.client.post("/api/mc/shutdown", headers=self.headers, json={})
        restart.assert_called_once()
        stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
