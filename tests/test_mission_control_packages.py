"""Package manager scan, validation, and install tests."""

from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from unittest import mock

from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.packages import PackageManager
from tests.common import REPO_ROOT
from tests.mc_helpers import mc_env


def _propset_zip(*, package_id: str = "testset", include_model: bool = True, manifest_kind: str = "propset") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "package.yaml",
            f"kind: {manifest_kind}\nid: {package_id}\nversion: 1.2.3\nlabel: Test Set\n",
        )
        archive.writestr("props.yaml", "box:\n  label: Box\n  model: model.glb\n  decorative: true\n")
        if include_model:
            archive.writestr("model.glb", b"glTF")
    return buffer.getvalue()


def _traversal_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("package.yaml", "kind: propset\nid: evil\n")
        archive.writestr("../escape.txt", "nope")
    return buffer.getvalue()


class PackageManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "data" / "propsets").mkdir(parents=True)
        (self.root / "data" / "cardsets").mkdir(parents=True)
        (self.root / "worlds").mkdir(parents=True)
        config = load_mc_config(env=mc_env(self.root), repo_root=self.root)
        self.manager = PackageManager(config, McAuditLog())

    def test_install_valid_propset(self) -> None:
        record = self.manager.install("propset", _propset_zip(), actor="op")
        self.assertEqual(record.id, "testset")
        self.assertEqual(record.version, "1.2.3")
        self.assertTrue((self.root / "data" / "propsets" / "testset" / "props.yaml").is_file())
        inventory = self.manager.inventory()
        self.assertEqual([item["id"] for item in inventory["propsets"]], ["testset"])

    def test_install_rejects_non_zip(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.install("propset", b"not a zip", actor="op")

    def test_install_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.install("propset", _traversal_zip(), actor="op")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_install_rejects_kind_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.install("propset", _propset_zip(manifest_kind="world"), actor="op")

    def test_install_validates_before_writing(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.install("propset", _propset_zip(include_model=False), actor="op")
        self.assertFalse((self.root / "data" / "propsets" / "testset").exists())

    def test_install_rejects_duplicate(self) -> None:
        self.manager.install("propset", _propset_zip(), actor="op")
        with self.assertRaises(ValueError):
            self.manager.install("propset", _propset_zip(), actor="op")

    def test_install_enforces_size_limit(self) -> None:
        with mock.patch("server.mission_control.packages.MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(ValueError):
                self.manager.install("propset", _propset_zip(), actor="op")

    def test_enable_disable_and_delete(self) -> None:
        self.manager.install("propset", _propset_zip(), actor="op")
        self.manager.set_enabled("propset", "testset", False, actor="op")
        self.assertFalse(self.manager.record("propset", "testset").enabled)
        self.manager.delete("propset", "testset", actor="op")
        self.assertIsNone(self.manager.record("propset", "testset"))
        self.assertFalse((self.root / "data" / "propsets" / "testset").exists())

    def test_delete_refuses_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.delete("propset", "..", actor="op")

    def test_inventory_reports_validation_errors(self) -> None:
        broken = self.root / "data" / "propsets" / "broken"
        broken.mkdir()
        (broken / "props.yaml").write_text("box:\n  label: Box\n  model: missing.glb\n", encoding="utf-8")
        inventory = self.manager.inventory()
        statuses = {item["id"]: item["validation"]["status"] for item in inventory["propsets"]}
        self.assertEqual(statuses.get("broken"), "error")

    def test_inventory_includes_running_version(self) -> None:
        inventory = self.manager.inventory()
        self.assertTrue(inventory["server_versions"])
        self.assertEqual(inventory["server_versions"][0]["id"], "running")


if __name__ == "__main__":
    unittest.main()
