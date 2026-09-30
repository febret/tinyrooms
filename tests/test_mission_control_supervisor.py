"""Supervisor spawn environment and lifecycle tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest import mock

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.registry import STATUS_STOPPED, InstanceRegistry
from server.mission_control.supervisor import Supervisor, route_slug
from tests.common import REPO_ROOT
from tests.mc_helpers import mc_env


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = None
        self.terminated = False
        self._exit = threading.Event()

    def wait(self, timeout: float | None = None) -> int:
        self._exit.wait(timeout)
        return 0

    def poll(self) -> int | None:
        return 0 if self._exit.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self._exit.set()

    def kill(self) -> None:
        self._exit.set()


class SupervisorEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = load_mc_config(env=mc_env(self.root), repo_root=REPO_ROOT)
        self.captured: dict[str, object] = {}
        self.processes: list[_FakeProcess] = []

        def fake_spawn(command, **kwargs):
            self.captured["command"] = command
            self.captured["env"] = kwargs["env"]
            process = _FakeProcess()
            self.processes.append(process)
            return process

        self.supervisor = Supervisor(
            self.config,
            InstanceRegistry(),
            McAuditLog(),
            spawn=fake_spawn,
        )

    def start(self, *, features: str = "") -> dict[str, str]:
        with mock.patch.dict(os.environ, {"TRSERVER_FEATURES": "mission-control", "TRSERVER_MC_PASSPHRASE": "op-secret"}):
            self.supervisor.start(
                name="tutorial",
                world_path=REPO_ROOT / "worlds" / "tutorial",
                users_path=self.root / "users",
                port=5099,
                features=features,
            )
        return self.captured["env"]  # type: ignore[return-value]

    def test_spawned_child_is_not_mission_control(self) -> None:
        env = self.start()
        self.assertEqual(env["TRSERVER_FEATURES"], "")
        self.assertNotIn("TRSERVER_MC_PASSPHRASE", env)
        self.assertEqual(env["TRSERVER_MC_ENDPOINT"], "127.0.0.1:8001")
        self.assertEqual(env["TRSERVER_WORLD_PATH"], str(REPO_ROOT / "worlds" / "tutorial"))
        self.assertEqual(env["TRSERVER_PORT"], "5099")

    def test_spawned_child_gets_a_base_path(self) -> None:
        env = self.start()
        self.assertEqual(env["TRSERVER_BASE_PATH"], "/tutorial")

    def test_operator_features_survive_but_mission_control_is_stripped(self) -> None:
        env = self.start(features="dev_sample_activity,mission-control")
        self.assertEqual(env["TRSERVER_FEATURES"], "dev_sample_activity")


class SupervisorLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = load_mc_config(env=mc_env(self.root), repo_root=REPO_ROOT)
        self.processes: list[_FakeProcess] = []

        def fake_spawn(command, **kwargs):
            process = _FakeProcess()
            self.processes.append(process)
            return process

        self.registry = InstanceRegistry()
        self.supervisor = Supervisor(self.config, self.registry, McAuditLog(), spawn=fake_spawn)

    def spawn(self, name: str = "tutorial", port: int = 5099):
        return self.supervisor.start(
            name=name,
            world_path=REPO_ROOT / "worlds" / "tutorial",
            users_path=self.root / "users",
            port=port,
        )

    def test_base_path_is_persisted_in_spawn_config(self) -> None:
        record = self.spawn()
        self.assertEqual(record.spawn_config["base_path"], "/tutorial")

    def test_restart_reuses_id_and_route(self) -> None:
        record = self.spawn()
        original_handle = record.process_handle
        restarted = self.supervisor.restart(record.instance_id)
        self.assertIsNotNone(restarted)
        self.assertEqual(restarted.instance_id, record.instance_id)
        self.assertEqual(restarted.base_path, "/tutorial")
        self.assertEqual(restarted.endpoint, record.endpoint)
        self.assertIsNot(restarted.process_handle, original_handle)

    def test_rename_updates_route_and_restarts(self) -> None:
        record = self.spawn()
        renamed = self.supervisor.rename(record.instance_id, "Sunny House")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed.name, "Sunny House")
        self.assertEqual(renamed.base_path, "/sunny-house")
        self.assertEqual(renamed.spawn_config["base_path"], "/sunny-house")
        self.assertEqual(renamed.spawn_config["name"], "Sunny House")

    def test_delete_removes_record(self) -> None:
        record = self.spawn()
        self.assertTrue(self.supervisor.delete(record.instance_id))
        self.assertIsNone(self.registry.get(record.instance_id))
        self.assertTrue(self.processes[0].terminated)

    def test_prepare_reboot_then_resume_pending(self) -> None:
        first = self.spawn("alpha", port=5101)
        second = self.spawn("beta", port=5102)
        resuming = self.supervisor.prepare_reboot()
        self.assertEqual(sorted(resuming), ["alpha", "beta"])
        for process in self.processes:
            self.assertTrue(process.terminated)
        resume_file = self.config.instances_path / "resume.json"
        payload = json.loads(resume_file.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["instances"]), 2)

        self.processes.clear()
        started = self.supervisor.resume_pending()
        self.assertEqual(sorted(started), sorted([first.instance_id, second.instance_id]))
        self.assertFalse(resume_file.exists())
        self.assertEqual(self.registry.get(first.instance_id).base_path, "/alpha")
        self.assertEqual(self.registry.get(second.instance_id).base_path, "/beta")


class RouteSlugTests(unittest.TestCase):
    def test_slugifies_and_deduplicates(self) -> None:
        self.assertEqual(route_slug("My World", set()), "my-world")
        self.assertEqual(route_slug("My World", {"my-world"}), "my-world-2")
        self.assertEqual(route_slug("!!!", set()), "world")


if __name__ == "__main__":
    unittest.main()
