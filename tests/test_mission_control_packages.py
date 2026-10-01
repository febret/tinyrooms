"""Shared-content inventory and server-version management tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.packages import PackageManager
from server.mission_control.registry import STATUS_STOPPED, InstanceRegistry
from tests.mc_helpers import mc_env


def _write_propset(root: Path, package_id: str = "sharedbox", *, model: bool = True) -> Path:
    directory = root / "propsets" / package_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "props.yaml").write_text(
        "box:\n  label: Box\n  model: model.glb\n  decorative: true\n",
        encoding="utf-8",
    )
    if model:
        (directory / "model.glb").write_bytes(b"glTF")
    return directory


def _write_world(root: Path, world_id: str) -> Path:
    directory = root / world_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "world.yaml").write_text(f"id: {world_id}\nentry_room: hub\n", encoding="utf-8")
    return directory


def _write_version(root: Path, version_id: str) -> Path:
    version = root / "versions" / version_id
    (version / "server").mkdir(parents=True, exist_ok=True)
    entry = {"major": 1, "minor": 0, "patch": 0}
    (version / "version.json").write_text(json.dumps([entry]) + "\n", encoding="utf-8")
    return version


class PackageManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        (self.root / "cardsets").mkdir()
        (self.root / "propsets").mkdir()
        (self.root / "worlds").mkdir()
        (self.root / "versions").mkdir()
        self.config = load_mc_config(env=mc_env(self.root), repo_root=self.root)
        self.registry = InstanceRegistry()
        self.manager = PackageManager(self.config, self.registry, McAuditLog())

    def _register(self, version: str) -> None:
        self.registry.register(
            {
                "instance_name": "world",
                "endpoint": f"https://127.0.0.1:{5000 + len(self.registry.list())}",
                "version": version,
                "world": {"id": "tutorial"},
            }
        )

    def test_inventory_lists_shared_propset(self) -> None:
        _write_propset(self.root)
        inventory = self.manager.inventory()
        self.assertEqual([item["id"] for item in inventory["propsets"]], ["sharedbox"])
        self.assertEqual(inventory["propsets"][0]["validation"]["status"], "ok")

    def test_inventory_reports_validation_errors(self) -> None:
        _write_propset(self.root, "broken", model=False)
        inventory = self.manager.inventory()
        statuses = {item["id"]: item["validation"]["status"] for item in inventory["propsets"]}
        self.assertEqual(statuses.get("broken"), "error")

    def test_inventory_excludes_version_bundled_content(self) -> None:
        bundled = self.root / "versions" / "1.0.0" / "data" / "propsets" / "bundled"
        bundled.mkdir(parents=True)
        (bundled / "props.yaml").write_text("box:\n  label: Box\n  model: model.glb\n", encoding="utf-8")
        (bundled / "model.glb").write_bytes(b"glTF")
        self.assertEqual(self.manager.inventory()["propsets"], [])

    def test_server_versions_reports_instance_counts(self) -> None:
        _write_version(self.root, "1.0.0")
        _write_version(self.root, "2.0.0")
        self._register("2.0.0")
        versions = {version["id"]: version for version in self.manager.server_versions()}
        self.assertTrue(versions["running"]["running"])
        self.assertFalse(versions["running"]["deletable"])
        self.assertEqual(versions["1.0.0"]["instance_count"], 0)
        self.assertTrue(versions["1.0.0"]["deletable"])
        self.assertEqual(versions["2.0.0"]["instance_count"], 1)
        self.assertFalse(versions["2.0.0"]["deletable"])

    def test_stopped_instance_counts_as_registered_not_running(self) -> None:
        _write_version(self.root, "1.0.0")
        self._register("1.0.0")
        instance_id = self.registry.list()[0].instance_id
        self.registry.set_status(instance_id, STATUS_STOPPED)
        version = {item["id"]: item for item in self.manager.server_versions()}["1.0.0"]
        self.assertEqual(version["instance_count"], 0)
        self.assertEqual(version["registered_count"], 1)
        self.assertFalse(version["deletable"])

    def test_delete_version_removes_directory_and_tarball(self) -> None:
        version = _write_version(self.root, "1.0.0")
        releases = self.root / "releases"
        releases.mkdir()
        tarball = releases / "tinyrooms-1.0.0.tar.gz"
        tarball.write_bytes(b"release")
        self.manager.delete_version("1.0.0", actor="op")
        self.assertFalse(version.exists())
        self.assertFalse(tarball.exists())

    def test_delete_version_refuses_in_use(self) -> None:
        _write_version(self.root, "1.0.0")
        self._register("1.0.0")
        with self.assertRaises(ValueError):
            self.manager.delete_version("1.0.0", actor="op")

    def test_delete_version_refuses_running(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.delete_version("running", actor="op")

    def test_delete_version_refuses_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.delete_version("..", actor="op")

    def test_resolve_version_running_and_installed(self) -> None:
        self.assertEqual(self.manager.resolve_version(None), self.root)
        self.assertEqual(self.manager.resolve_version("running"), self.root)
        version = _write_version(self.root, "1.0.0")
        self.assertEqual(self.manager.resolve_version("1.0.0"), version)
        with self.assertRaises(ValueError):
            self.manager.resolve_version("..")
        with self.assertRaises(ValueError):
            self.manager.resolve_version("missing")

    def test_resolve_world_prefers_shared(self) -> None:
        shared = _write_world(self.root / "worlds", "town")
        version = _write_version(self.root, "1.0.0")
        bundled = _write_world(version / "worlds", "town")
        self.assertEqual(self.manager.resolve_world("1.0.0", "town"), shared)
        self.assertEqual(self.manager.resolve_world(None, "town"), shared)
        self.assertNotEqual(self.manager.resolve_world("1.0.0", "town"), bundled)

    def test_resolve_world_uses_version_bundle_when_not_shared(self) -> None:
        version = _write_version(self.root, "1.0.0")
        bundled = _write_world(version / "worlds", "garden")
        self.assertEqual(self.manager.resolve_world("1.0.0", "garden"), bundled)
        with self.assertRaises(ValueError):
            self.manager.resolve_world("1.0.0", "missing")

    def test_worlds_for_includes_shared_and_version(self) -> None:
        _write_world(self.root / "worlds", "town")
        version = _write_version(self.root, "1.0.0")
        _write_world(version / "worlds", "garden")
        worlds = {world["id"]: world for world in self.manager.worlds_for("1.0.0")}
        self.assertEqual(worlds["town"]["source"], "shared")
        self.assertEqual(worlds["garden"]["source"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
