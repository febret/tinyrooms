"""World-side mission-control client and API tests."""

from __future__ import annotations

import asyncio
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
from server.mc_api import MC_CAPABILITIES
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


class _FakeWorld:
    id = "tutorial"
    label = "The Little House"


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
    def test_register_and_heartbeat(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path.endswith("/register"):
                payload = json.loads(request.content)
                assert payload["instance_name"] == "test-world"
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

    def test_capabilities_cover_admin_commands(self) -> None:
        self.assertIn("admin.status", MC_CAPABILITIES)

    def test_command_unknown_actor(self) -> None:
        response = self.client.post(
            "/api/mc/command",
            headers=self.headers,
            json={"command": "\\status", "actor": "ghost"},
        )
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["code"], "actor_unknown")

    def test_command_dispatch(self) -> None:
        self._create_admin()
        response = self.client.post(
            "/api/mc/command",
            headers=self.headers,
            json={"command": "\\status", "actor": "mcadmin"},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["message"], "Server status loaded.")

    def test_resync_bumps_revision(self) -> None:
        response = self.client.post("/api/mc/resync", headers=self.headers, json={"actor": "mcadmin"})
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
