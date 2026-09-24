"""Supervisor spawn environment tests."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.registry import InstanceRegistry
from server.mission_control.supervisor import Supervisor
from tests.common import REPO_ROOT
from tests.mc_helpers import mc_env


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        return None


class SupervisorEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = load_mc_config(env=mc_env(self.root), repo_root=REPO_ROOT)
        self.captured: dict[str, object] = {}

        def fake_spawn(command, **kwargs):
            self.captured["command"] = command
            self.captured["env"] = kwargs["env"]
            return _FakeProcess()

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

    def test_operator_features_survive_but_mission_control_is_stripped(self) -> None:
        env = self.start(features="dev_sample_activity,mission-control")
        self.assertEqual(env["TRSERVER_FEATURES"], "dev_sample_activity")


if __name__ == "__main__":
    unittest.main()
