"""Mission-control instance lifecycle route tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from starlette.testclient import TestClient

from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from tests.common import REPO_ROOT
from tests.mc_helpers import MC_BASE_URL, McHttpTestCase, mc_env


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = None
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class InstanceLifecycleTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.app.state.mc
        self.spawn_patch = mock.patch.object(self.runtime.supervisor, "_spawn_process", side_effect=lambda config: _FakeProcess())
        self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)

    def add_spawned(self, name: str = "tutorial", port: int = 5099, base_path: str = "/tutorial"):
        return self.runtime.registry.register_spawned(
            name=name,
            endpoint=f"https://127.0.0.1:{port}",
            instance_dir=str(self.root / "instance"),
            process_handle=_FakeProcess(),
            base_path=base_path,
            spawn_config={
                "name": name,
                "world_path": str(REPO_ROOT / "worlds" / "tutorial"),
                "worldstate_path": str(self.root / "worldstate.sqlite3"),
                "users_path": str(self.root / "users"),
                "host": "127.0.0.1",
                "port": port,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": base_path,
            },
        )

    def register_external(self, endpoint: str = "https://127.0.0.1:59999") -> str:
        response = self.client.post(
            "/api/mc/register",
            json={"instance_name": "remote", "endpoint": endpoint, "base_path": "/remote"},
            headers={"x-mc-token": self.config.token},
        )
        return response.json()["instance_id"]

    def test_restart_spawned_keeps_id(self) -> None:
        record = self.add_spawned()
        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/restart",
            headers=self.csrf_headers(),
            json={},
        )
        self.assertEqual(response.status_code, 200)
        server = response.json()["server"]
        self.assertEqual(server["instance_id"], record.instance_id)
        self.assertEqual(server["base_path"], "/tutorial")

    def test_rename_spawned_updates_route(self) -> None:
        record = self.add_spawned()
        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/rename",
            headers=self.csrf_headers(),
            json={"name": "Sunny House"},
        )
        self.assertEqual(response.status_code, 200)
        server = response.json()["server"]
        self.assertEqual(server["name"], "Sunny House")
        self.assertEqual(server["base_path"], "/sunny-house")

    def test_delete_spawned_removes_record(self) -> None:
        record = self.add_spawned()
        response = self.client.request(
            "DELETE",
            f"/api/mission-control/servers/{record.instance_id}",
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.runtime.registry.get(record.instance_id))

    def test_rename_external_rejected(self) -> None:
        instance_id = self.register_external()
        response = self.client.post(
            f"/api/mission-control/servers/{instance_id}/rename",
            headers=self.csrf_headers(),
            json={"name": "Nope"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "rename_external")

    def test_restart_external_unreachable_returns_502(self) -> None:
        instance_id = self.register_external()
        response = self.client.post(
            f"/api/mission-control/servers/{instance_id}/restart",
            headers=self.csrf_headers(),
            json={},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "unreachable")

    def test_delete_external_removes_record(self) -> None:
        instance_id = self.register_external()
        response = self.client.request(
            "DELETE",
            f"/api/mission-control/servers/{instance_id}",
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.runtime.registry.get(instance_id))

    def test_reboot_requires_keepalive(self) -> None:
        response = self.client.post("/api/mission-control/reboot", headers=self.csrf_headers(), json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "reboot_unconfigured")


class RebootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        config = load_mc_config(
            env=mc_env(self.root, TRSERVER_MC_KEEPALIVE=str(self.root / "keepalive.sh")),
            repo_root=REPO_ROOT,
        )
        self.app = create_mc_app(config)
        context = TestClient(self.app, base_url=MC_BASE_URL)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.client.post("/api/mission-control/auth/login", json={"passphrase": "letmein"}, headers={"origin": MC_BASE_URL})
        self.runtime = self.app.state.mc

    def csrf_headers(self) -> dict[str, str]:
        return {"origin": MC_BASE_URL, "x-csrf-token": self.client.cookies.get("tr_mc_csrf", "")}

    def test_reboot_records_resume_and_launches_keepalive(self) -> None:
        self.runtime.registry.register_spawned(
            name="tutorial",
            endpoint="https://127.0.0.1:5099",
            instance_dir=str(self.root / "instance"),
            process_handle=_FakeProcess(),
            base_path="/tutorial",
            spawn_config={
                "name": "tutorial",
                "world_path": str(REPO_ROOT / "worlds" / "tutorial"),
                "worldstate_path": str(self.root / "worldstate.sqlite3"),
                "users_path": str(self.root / "users"),
                "host": "127.0.0.1",
                "port": 5099,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": "/tutorial",
            },
        )
        with mock.patch("server.mission_control.routes._launch_keepalive") as launcher, \
                mock.patch("server.mission_control.routes.threading.Timer"):
            response = self.client.post("/api/mission-control/reboot", headers=self.csrf_headers(), json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resuming"], ["tutorial"])
        launcher.assert_called_once()
        self.assertTrue((self.runtime.config.instances_path / "resume.json").is_file())


if __name__ == "__main__":
    unittest.main()
