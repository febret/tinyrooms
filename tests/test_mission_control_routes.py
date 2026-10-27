"""Mission-control instance lifecycle route tests."""

from __future__ import annotations

from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import httpx
from starlette.testclient import TestClient

from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from server.mission_control.registry import STATUS_RUNNING, STATUS_STOPPED
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

    def _free_port(self) -> int:
        used = {
            int(record.spawn_config["port"])
            for record in self.runtime.registry.list()
            if record.spawn_config and record.spawn_config.get("port") is not None
        }
        for port in range(5000, 6000):
            if port in used:
                continue
            check = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                check.bind(("127.0.0.1", port))
            except OSError:
                continue
            finally:
                check.close()
            return port
        raise AssertionError("could not find a free test port")

    def add_spawned(self, name: str = "tutorial", port: int | None = None, base_path: str = "/tutorial"):
        if port is None:
            port = self._free_port()
        (self.root / "instance").mkdir(exist_ok=True)
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

    def occupy_port(self, port: int) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", port))
        self.addCleanup(listener.close)

    def register_external(self, endpoint: str = "https://127.0.0.1:59999") -> str:
        response = self.client.post(
            "/api/mc/register",
            json={"instance_name": "remote", "endpoint": endpoint, "base_path": "/remote"},
            headers={"x-mc-token": self.config.token},
        )
        return response.json()["instance_id"]

    def test_register_rejects_injected_base_path(self) -> None:
        response = self.client.post(
            "/api/mc/register",
            json={
                "instance_name": "evil",
                "endpoint": "https://127.0.0.1:60001",
                "base_path": "x\n    location /evil { return 200; }\n",
            },
            headers={"x-mc-token": self.config.token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "base_path_invalid")

    def test_restart_spawned_keeps_id(self) -> None:
        record = self.add_spawned()
        expected_port = record.spawn_config["port"]
        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/restart",
            headers=self.csrf_headers(),
            json={},
        )
        self.assertEqual(response.status_code, 200)
        server = response.json()["server"]
        self.assertEqual(server["instance_id"], record.instance_id)
        self.assertEqual(server["base_path"], "/tutorial")
        self.assertEqual(record.spawn_config["port"], expected_port)
        self.assertEqual(server["endpoint"], f"https://127.0.0.1:{expected_port}")

    def test_rename_spawned_preserves_route(self) -> None:
        record = self.add_spawned()
        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/rename",
            headers=self.csrf_headers(),
            json={"name": "Sunny House"},
        )
        self.assertEqual(response.status_code, 200)
        server = response.json()["server"]
        self.assertEqual(server["name"], "Sunny House")
        self.assertEqual(server["base_path"], "/tutorial")

    def test_delete_spawned_removes_record(self) -> None:
        record = self.add_spawned()
        response = self.client.request(
            "DELETE",
            f"/api/mission-control/servers/{record.instance_id}",
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.runtime.registry.get(record.instance_id))
        retired = self.runtime.retired.get(record.instance_id)
        self.assertIsNotNone(retired)
        self.assertIsNone(retired["successor_instance_id"])

    def test_delete_with_successor_reassigns_saved_destinations(self) -> None:
        record = self.add_spawned()
        record.world_id = "tutorial"
        successor = self.add_spawned(name="successor")
        successor.world_id = "tutorial"
        successor.registered_at = "2026-01-01T00:00:00+00:00"
        self.runtime.registry.set_status(successor.instance_id, "running")
        account = self.runtime.profiles.create_account("player", "password123!", "tutorial", "hub")
        self.runtime.profiles.remember_instance(account.id, record.instance_id)

        response = self.client.request(
            "DELETE",
            f"/api/mission-control/servers/{record.instance_id}"
            f"?successor_instance_id={successor.instance_id}&reassign_players=true",
            headers=self.csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reassigned"], 1)
        profile = self.runtime.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, successor.instance_id)
        retired = self.runtime.retired.get(record.instance_id)
        self.assertEqual(retired["successor_instance_id"], successor.instance_id)

    def test_user_destination_repair_updates_profile(self) -> None:
        record = self.add_spawned()
        record.world_id = "tutorial"
        record.client_url = f"https://127.0.0.1:{int(record.spawn_config['port'])}/tutorial"
        record.registered_at = "2026-01-01T00:00:00+00:00"
        self.runtime.registry.set_status(record.instance_id, "running")
        account = self.runtime.profiles.create_account("player", "password123!", "tutorial", "hub")
        self.runtime.profiles.remember_instance(account.id, "mc-missing")
        original = self.runtime.http
        self.runtime.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True, "world_id": "tutorial", "instance_id": record.instance_id},
                )
            )
        )
        self.addCleanup(lambda: __import__("asyncio").run(self.runtime.http.aclose()))
        self.addCleanup(lambda: __import__("asyncio").run(original.aclose()))

        response = self.client.post(
            f"/api/mission-control/users/{account.id}/destination",
            headers=self.csrf_headers(),
            json={"instance_id": record.instance_id},
        )

        self.assertEqual(response.status_code, 200)
        profile = self.runtime.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, record.instance_id)

    def test_deregister_refreshes_world_map(self) -> None:
        record = self.add_spawned()
        update = mock.Mock()
        self.runtime.world_map.update = update

        response = self.client.post(
            "/api/mc/deregister",
            headers={"x-mc-token": self.config.token},
            json={"instance_id": record.instance_id},
        )

        self.assertEqual(response.status_code, 200)
        update.assert_called_once()

    def test_rename_external_rejected(self) -> None:
        instance_id = self.register_external()
        response = self.client.post(
            f"/api/mission-control/servers/{instance_id}/rename",
            headers=self.csrf_headers(),
            json={"name": "Nope"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "rename_external")

    def test_restart_reassigns_a_conflicting_saved_port(self) -> None:
        record = self.add_spawned()
        saved_port = int(record.spawn_config["port"])
        self.occupy_port(saved_port)

        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/restart",
            headers=self.csrf_headers(),
            json={},
        )

        self.assertEqual(response.status_code, 200)
        server = response.json()["server"]
        self.assertNotEqual(server["endpoint"], f"https://127.0.0.1:{saved_port}")
        self.assertNotEqual(record.spawn_config["port"], saved_port)
        self.assertTrue(5000 <= record.spawn_config["port"] <= 5999)

    def test_start_stopped_instance_reassigns_a_conflicting_saved_port(self) -> None:
        record = self.add_spawned()
        saved_port = int(record.spawn_config["port"])
        self.runtime.registry.set_status(record.instance_id, STATUS_STOPPED)
        self.occupy_port(saved_port)

        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/start",
            headers=self.csrf_headers(),
            json={},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["server"]["endpoint"], f"https://127.0.0.1:{saved_port}")
        self.assertNotEqual(record.spawn_config["port"], saved_port)

    def test_resume_reassigns_a_port_held_after_reboot(self) -> None:
        record = self.add_spawned()
        saved_port = int(record.spawn_config["port"])
        self.runtime.registry.set_status(record.instance_id, STATUS_RUNNING)
        self.runtime.supervisor.prepare_reboot()
        self.occupy_port(saved_port)

        resumed = self.runtime.supervisor.resume_pending()

        self.assertIn(record.instance_id, resumed)
        resumed_record = self.runtime.registry.get(record.instance_id)
        self.assertIsNotNone(resumed_record)
        self.assertNotEqual(resumed_record.spawn_config["port"], saved_port)
        self.assertNotEqual(resumed_record.endpoint, f"https://127.0.0.1:{saved_port}")

    def test_change_instance_version_updates_saved_configuration(self) -> None:
        record = self.add_spawned()
        record.world_id = "tutorial"

        response = self.client.post(
            f"/api/mission-control/servers/{record.instance_id}/version",
            headers=self.csrf_headers(),
            json={"version": "running"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.spawn_config["version_id"], "running")
        self.assertEqual(response.json()["server"]["version_id"], "running")
        self.assertEqual(Path(record.spawn_config["world_path"]), REPO_ROOT / "worlds" / "tutorial")

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
