"""Mission-control supervisor process-ownership tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.registry import (
    STATUS_RUNNING,
    STATUS_STOPPED,
    InstanceRegistry,
)
from server.mission_control.supervisor import (
    RestoredChildProcess,
    Supervisor,
    _proc_identity_matches,
)
from tests.common import REPO_ROOT
from tests.mc_helpers import McHttpTestCase, mc_env


class _FakeProcess:
    def __init__(self, pid: int | None = 4242) -> None:
        self.pid = pid
        self.stdout = None
        self.terminated = False
        self.killed = False
        self._exited = threading.Event()

    def poll(self) -> int | None:
        return 0 if self._exited.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self._exited.set()

    def kill(self) -> None:
        self.killed = True
        self._exited.set()

    def wait(self, timeout: float | None = None) -> int:
        if self._exited.wait(timeout):
            return 0
        raise subprocess.TimeoutExpired(["fake"], timeout)


class SupervisorPidTests(unittest.TestCase):
    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.config = load_mc_config(env=mc_env(self.root), repo_root=REPO_ROOT)
        self.registry = InstanceRegistry()
        self.audit = McAuditLog()

    def make_supervisor(self, **kwargs: object) -> Supervisor:
        return Supervisor(self.config, self.registry, self.audit, **kwargs)  # type: ignore[arg-type]

    def spawn_config(self, **overrides: object) -> dict[str, object]:
        config: dict[str, object] = {
            "instance_id": "mc-pidtest",
            "client_url": "https://127.0.0.1:5099/pidtest",
            "name": "pidtest",
            "world_path": str(REPO_ROOT / "worlds" / "tutorial"),
            "worldstate_path": str(self.root / "worldstate.sqlite3"),
            "users_path": str(self.root / "users"),
            "host": "127.0.0.1",
            "port": 5099,
            "features": "",
            "admins": "",
            "mods": "*",
            "base_path": "/pidtest",
            "version_path": "",
            "version_id": "running",
        }
        config.update(overrides)
        return config

    def write_identity(self, instance_id: str, config: dict[str, object]) -> Path:
        directory = self.config.instances_path / instance_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "instance.json").write_text(
            json.dumps({"instance_id": instance_id, "spawn_config": config}, indent=2) + "\n",
            encoding="utf-8",
        )
        return directory

    def test_start_persists_child_pid(self) -> None:
        supervisor = self.make_supervisor(spawn=lambda *args, **kwargs: _FakeProcess(pid=7777))
        record = supervisor.start(
            name="pidtest",
            world_path=REPO_ROOT / "worlds" / "tutorial",
            host="127.0.0.1",
            port=5099,
        )
        self.assertEqual(record.spawn_config["pid"], 7777)
        saved = json.loads((Path(record.instance_dir) / "instance.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["spawn_config"]["pid"], 7777)

    def test_restored_child_is_adopted_not_orphaned(self) -> None:
        adopted = _FakeProcess(pid=4321)
        self.write_identity("mc-adopted", self.spawn_config(instance_id="mc-adopted", pid=4321))
        with mock.patch.object(Supervisor, "_adopt_restored_process", return_value=adopted):
            supervisor = self.make_supervisor()
        record = self.registry.get("mc-adopted")
        self.assertIsNotNone(record)
        self.assertIs(record.process_handle, adopted)
        self.assertTrue(supervisor.stop("mc-adopted"))
        self.assertTrue(adopted.terminated)
        self.assertEqual(self.registry.get("mc-adopted").status, STATUS_STOPPED)

    def test_change_version_stops_restored_child_before_respawning(self) -> None:
        adopted = _FakeProcess(pid=4321)
        self.write_identity("mc-switch", self.spawn_config(instance_id="mc-switch", pid=4321))
        spawned: list[_FakeProcess] = []
        with mock.patch.object(Supervisor, "_adopt_restored_process", return_value=adopted):
            supervisor = self.make_supervisor(
                spawn=lambda *args, **kwargs: spawned.append(_FakeProcess(pid=9999)) or spawned[-1]
            )
        record = self.registry.get("mc-switch")
        self.registry.set_status("mc-switch", STATUS_RUNNING)
        self.registry.heartbeat("mc-switch", uptime_seconds=1.0)
        updated = supervisor.change_version(
            "mc-switch",
            version_id="v2",
            version_path=REPO_ROOT,
            world_path=REPO_ROOT / "worlds" / "tutorial",
        )
        self.assertIsNotNone(updated)
        self.assertTrue(adopted.terminated)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(record.spawn_config["version_id"], "v2")
        self.assertEqual(record.spawn_config["pid"], 9999)

    def test_restart_refuses_unmanageable_live_child(self) -> None:
        supervisor = self.make_supervisor()
        record = self.registry.register_spawned(
            instance_id="mc-ghost",
            name="ghost",
            endpoint="https://127.0.0.1:5099",
            instance_dir=str(self.root / "ghost"),
            process_handle=None,
            base_path="/ghost",
            spawn_config=self.spawn_config(instance_id="mc-ghost"),
        )
        self.registry.set_status(record.instance_id, STATUS_RUNNING)
        with mock.patch.object(supervisor, "_saved_port_occupied", return_value=True):
            with mock.patch.object(supervisor, "_spawn_process") as spawn:
                self.assertIsNone(supervisor.restart("mc-ghost"))
                spawn.assert_not_called()
            self.assertFalse(supervisor.stop("mc-ghost"))

    def test_revive_clears_reported_build(self) -> None:
        record = self.registry.register_spawned(
            instance_id="mc-rev",
            name="rev",
            endpoint="https://127.0.0.1:5099",
            instance_dir=str(self.root / "rev"),
            process_handle=None,
            base_path="/rev",
            spawn_config=self.spawn_config(instance_id="mc-rev"),
        )
        record.version = "1.0.0"
        self.registry.revive("mc-rev", process_handle=_FakeProcess())
        self.assertIsNone(self.registry.get("mc-rev").version)

    def test_restored_handle_never_signals_unverified_pid(self) -> None:
        handle = RestoredChildProcess(999999, instance_id="mc-nope", port=5099)
        with mock.patch(
            "server.mission_control.supervisor._pid_alive", return_value=False
        ):
            self.assertEqual(handle.poll(), -1)
            handle.terminate()
            handle.kill()
            self.assertEqual(handle.wait(timeout=0.01), 0)

    def test_restored_handle_wait_times_out_while_child_lives(self) -> None:
        handle = RestoredChildProcess(999999, instance_id="mc-nope", port=5099)
        with mock.patch(
            "server.mission_control.supervisor._pid_alive", return_value=True
        ), mock.patch(
            "server.mission_control.supervisor._proc_identity_matches",
            return_value=True,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                handle.wait(timeout=0.01)

    @unittest.skipUnless(sys.platform == "linux", "requires /proc")
    def test_proc_identity_match_requires_managed_environment(self) -> None:
        self.assertFalse(_proc_identity_matches(1, instance_id="mc-nope", port=5099))


class FleetPidGuardTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.app.state.mc

    def register_pid_guarded(self) -> str:
        return self.runtime.registry.register_spawned(
            name="guarded",
            endpoint="https://127.0.0.1:5099",
            instance_dir=str(self.root / "guarded"),
            process_handle=None,
            base_path="/guarded",
            spawn_config={
                "name": "guarded",
                "world_path": str(REPO_ROOT / "worlds" / "tutorial"),
                "worldstate_path": str(self.root / "worldstate.sqlite3"),
                "users_path": str(self.root / "users"),
                "host": "127.0.0.1",
                "port": 5099,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": "/guarded",
                "client_url": "https://127.0.0.1:5099/guarded",
                "pid": 1111,
            },
        ).instance_id

    def test_stale_registration_is_rejected(self) -> None:
        instance_id = self.register_pid_guarded()
        response = self.client.post(
            "/api/mc/register",
            json={
                "instance_name": "guarded",
                "instance_id": instance_id,
                "endpoint": "https://127.0.0.1:5099",
                "base_path": "/guarded",
                "client_url": "https://127.0.0.1:5099/guarded",
                "version": "9.9.9",
                "pid": 2222,
            },
            headers={"x-mc-token": self.config.token},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "stale_instance")
        self.assertIsNone(self.runtime.registry.get(instance_id).version)

    def test_matching_pid_registers_and_heartbeats(self) -> None:
        instance_id = self.register_pid_guarded()
        response = self.client.post(
            "/api/mc/register",
            json={
                "instance_name": "guarded",
                "instance_id": instance_id,
                "endpoint": "https://127.0.0.1:5099",
                "base_path": "/guarded",
                "client_url": "https://127.0.0.1:5099/guarded",
                "version": "2.1.0",
                "pid": 1111,
            },
            headers={"x-mc-token": self.config.token},
        )
        self.assertEqual(response.status_code, 200)
        heartbeat = self.client.post(
            "/api/mc/heartbeat",
            json={"instance_id": instance_id, "uptime_seconds": 3, "pid": 1111},
            headers={"x-mc-token": self.config.token},
        )
        self.assertTrue(heartbeat.json()["ok"])

    def test_stale_heartbeat_and_deregister_are_ignored(self) -> None:
        instance_id = self.register_pid_guarded()
        stale = self.client.post(
            "/api/mc/heartbeat",
            json={"instance_id": instance_id, "uptime_seconds": 3, "pid": 2222},
            headers={"x-mc-token": self.config.token},
        )
        self.assertEqual(stale.json()["code"], "stale_instance")
        deregister = self.client.post(
            "/api/mc/deregister",
            json={"instance_id": instance_id, "pid": 2222},
            headers={"X-MC-Token": self.config.token},
        )
        self.assertTrue(deregister.json()["ok"])
        self.assertNotEqual(self.runtime.registry.get(instance_id).status, STATUS_STOPPED)
        live = self.client.post(
            "/api/mc/deregister",
            json={"instance_id": instance_id, "pid": 1111},
            headers={"X-MC-Token": self.config.token},
        )
        self.assertTrue(live.json()["ok"])
        self.assertEqual(self.runtime.registry.get(instance_id).status, STATUS_STOPPED)


if __name__ == "__main__":
    unittest.main()
