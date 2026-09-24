"""In-process mission-control <-> world-server integration round-trip."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx
from starlette.testclient import TestClient

from server.app import create_app
from server.config import load_config
from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from tests.common import REPO_ROOT
from tests.mc_helpers import MC_BASE_URL, mc_env


class MissionControlIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)

        world_env = {
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open",
            "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
            "TRSERVER_WORLDSTATE_PATH": str(root / "world" / "worldstate.sqlite3"),
            "TRSERVER_USERS_PATH": str(root / "world" / "users"),
            "TRSERVER_FEATURES": "dev_sample_activity",
            "TRSERVER_MODS": "infinite-bedrooms",
            "TRSERVER_ADMINS": "mcadmin",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": "5000",
            "TRSERVER_MC_ENDPOINT": "127.0.0.1:8001",
            "TRSERVER_MC_TOKEN": "shared",
            "TRSERVER_MC_INSECURE_TLS": "1",
        }
        self.world_app = create_app(load_config(env=world_env, repo_root=REPO_ROOT))
        self.world_context = TestClient(self.world_app, base_url="https://127.0.0.1:5000")
        self.world_client = self.world_context.__enter__()
        self.addCleanup(self.world_context.__exit__, None, None, None)
        runtime = self.world_app.state.runtime
        runtime.profiles.create_account("mcadmin", "password123!", runtime.world.id, runtime.world.entry_room_id)

        mc_config = load_mc_config(env=mc_env(root / "mc"), repo_root=REPO_ROOT)
        self.mc_app = create_mc_app(mc_config)
        self.mc_context = TestClient(self.mc_app, base_url=MC_BASE_URL)
        self.mc_client = self.mc_context.__enter__()
        self.addCleanup(self.mc_context.__exit__, None, None, None)
        self.mc_runtime = self.mc_app.state.mc

        original = self.mc_runtime.http
        self.mc_runtime.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.world_app),
            base_url="https://127.0.0.1:5000",
        )
        self.addCleanup(lambda: asyncio.run(self.mc_runtime.http.aclose()))
        self.addCleanup(lambda: asyncio.run(original.aclose()))

        self.mc_client.post(
            "/api/mission-control/auth/login",
            json={"passphrase": "letmein"},
            headers={"origin": MC_BASE_URL},
        )
        self.csrf = self.mc_client.cookies.get("tr_mc_csrf", "")

    def _operator_headers(self) -> dict[str, str]:
        return {"origin": MC_BASE_URL, "x-csrf-token": self.csrf}

    def test_full_round_trip(self) -> None:
        registered = self.mc_client.post(
            "/api/mc/register",
            headers={"X-MC-Token": "shared"},
            json={
                "instance_name": "tutorial",
                "endpoint": "https://127.0.0.1:5000",
                "version": "1.0.0",
                "protocol_version": 1,
                "world": {"id": "tutorial", "label": "The Little House"},
                "started_at": "2026-01-01T00:00:00+00:00",
            },
        )
        payload = registered.json()
        self.assertTrue(payload["ok"])
        instance_id = payload["instance_id"]

        heartbeat = self.mc_client.post(
            "/api/mc/heartbeat",
            headers={"X-MC-Token": "shared"},
            json={"instance_id": instance_id, "uptime_seconds": 5, "users_online": 0, "world_id": "tutorial"},
        )
        self.assertTrue(heartbeat.json()["ok"])

        servers = self.mc_client.get("/api/mission-control/servers").json()
        self.assertEqual(servers["summary"]["running"], 1)
        self.assertEqual(servers["servers"][0]["instance_id"], instance_id)

        detail = self.mc_client.get(f"/api/mission-control/servers/{instance_id}").json()
        self.assertEqual(detail["server"]["stats"]["world"]["id"], "tutorial")

        command = self.mc_client.post(
            f"/api/mission-control/servers/{instance_id}/command",
            headers=self._operator_headers(),
            json={"command": "\\status"},
        ).json()
        self.assertTrue(command["ok"])
        self.assertEqual(command["result"]["result"]["message"], "Server status loaded.")

        resync = self.mc_client.post(
            f"/api/mission-control/servers/{instance_id}/resync",
            headers=self._operator_headers(),
            json={},
        ).json()
        self.assertTrue(resync["ok"])
        self.assertEqual(resync["result"]["refreshed"], 1)

    def test_packages_and_users_endpoints(self) -> None:
        packages = self.mc_client.get("/api/mission-control/packages").json()["packages"]
        self.assertTrue(any(world["id"] == "tutorial" for world in packages["worlds"]))
        self.mc_runtime.profiles.create_account("mcuser", "password123!", "tutorial", "hub")
        users = self.mc_client.get("/api/mission-control/users?q=mcuser").json()["users"]
        self.assertEqual([user["username"] for user in users], ["mcuser"])

    def test_capability_rejection(self) -> None:
        registered = self.mc_client.post(
            "/api/mc/register",
            headers={"X-MC-Token": "shared"},
            json={"instance_name": "tutorial", "endpoint": "https://127.0.0.1:5000", "world": {"id": "tutorial"}},
        ).json()
        response = self.mc_client.post(
            f"/api/mission-control/servers/{registered['instance_id']}/command",
            headers=self._operator_headers(),
            json={"command": "\\explode"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "capability_unknown")


if __name__ == "__main__":
    unittest.main()
