"""Same-origin world path and persisted identity migration tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.registry import InstanceRegistry
from server.mission_control.supervisor import Supervisor, same_origin_base_path, same_origin_client_url
from tests.common import REPO_ROOT
from tests.mc_helpers import mc_env


class SameOriginWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = load_mc_config(
            env=mc_env(
                self.root,
                TRSERVER_MC_SAME_ORIGIN_WORLDS="1",
                TRSERVER_MC_WORLD_MAP=str(self.root / "worlds.map"),
                TRSERVER_MC_WORLD_MAP_RELOAD="true",
                TRSERVER_MC_PUBLIC_ORIGIN="https://tinyrooms.app",
                TRSERVER_MC_INSTANCE_PUBLIC_HOST="tinyrooms.app",
                TRSERVER_MC_INSTANCE_HOST="127.0.0.1",
            ),
            repo_root=REPO_ROOT,
        )

    def test_path_helpers_include_mc_base_path(self) -> None:
        self.assertEqual(same_origin_base_path("", "mc-one"), "/world/mc-one")
        self.assertEqual(same_origin_base_path("/base", "mc-one"), "/base/world/mc-one")
        self.assertEqual(
            same_origin_client_url("", "tinyrooms.app", "mc-one"),
            "https://tinyrooms.app/world/mc-one/",
        )
        self.assertEqual(
            same_origin_client_url("/base", "tinyrooms.app", "mc-one"),
            "https://tinyrooms.app/base/world/mc-one/",
        )

    def test_restore_migrates_legacy_identity(self) -> None:
        instance_dir = self.config.instances_path / "mc-legacy"
        instance_dir.mkdir(parents=True)
        identity = instance_dir / "instance.json"
        identity.write_text(
            json.dumps({
                "instance_id": "mc-legacy",
                "spawn_config": {
                    "instance_id": "mc-legacy",
                    "name": "tutorial",
                    "world_path": str(self.root / "world"),
                    "worldstate_path": str(instance_dir / "worldstate.sqlite3"),
                    "users_path": str(self.config.users_path),
                    "host": "0.0.0.0",
                    "port": 10000,
                    "features": "",
                    "admins": "",
                    "mods": "*",
                    "base_path": "",
                    "client_url": "https://tinyrooms.febret.com:10000",
                },
            }),
            encoding="utf-8",
        )

        registry = InstanceRegistry()
        Supervisor(self.config, registry, McAuditLog())
        record = registry.get("mc-legacy")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.endpoint, "https://127.0.0.1:10000")
        self.assertEqual(record.base_path, "/world/mc-legacy")
        self.assertEqual(record.client_url, "https://tinyrooms.app/world/mc-legacy/")
        persisted = json.loads(identity.read_text(encoding="utf-8"))["spawn_config"]
        self.assertEqual(persisted["host"], "127.0.0.1")
        self.assertEqual(persisted["base_path"], "/world/mc-legacy")
        self.assertEqual(persisted["client_url"], "https://tinyrooms.app/world/mc-legacy/")


if __name__ == "__main__":
    unittest.main()
