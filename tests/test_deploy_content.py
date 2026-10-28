"""Tests for deployment content selection, hashing, and packaging."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest import mock
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

SPEC = importlib.util.spec_from_file_location("deploy_tool_content", TOOLS / "deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)

from deploy_content import (  # noqa: E402
    content_hash,
    load_content_selection,
    package_filename,
    split_package_stem,
)
from server.mission_control.registry import InstanceRegistry  # noqa: E402
from server.version import deployment_version_hash, version_info  # noqa: E402
import start_multiworld  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ContentSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(
            self.root / "worlds" / "alpha-dir" / "world.yaml",
            "id: alpha\nrequires_mods: [mod-a]\nrequires_cardsets: [set-a]\n"
            "requires_propsets: [props-a]\n",
        )
        _write(
            self.root / "worlds" / "alpha-dir" / "rooms" / "rooms.yaml",
            "hub:\n  props:\n    chair:\n      prop: alpha-chair\n",
        )
        _write(self.root / "worlds" / "beta" / "world.yaml", "id: beta\n")
        _write(self.root / "mods" / "mod-a" / "mod.yaml", "id: mod-a\nrequires: [mod-b]\n")
        _write(self.root / "mods" / "mod-b" / "mod.yaml", "id: mod-b\n")
        _write(self.root / "mods" / "mod-unused" / "mod.yaml", "id: mod-unused\n")
        for cardset in ("base", "set-a", "set-b"):
            _write(self.root / "data" / "cardsets" / cardset / "cards.yaml", "{}\n")
        _write(self.root / "data" / "cardsets" / "card-backgrounds" / "bg.png", "bg")
        _write(self.root / "data" / "propsets" / "props-a" / "props.yaml", "alpha-chair: {}\n")
        _write(self.root / "data" / "propsets" / "props-b" / "props.yaml", "beta-chair: {}\n")
        self.config = self.root / "content.json"
        self.config.write_text(
            json.dumps(
                {
                    "worlds": [
                        {"id": "alpha", "enabled": True, "path": "worlds/alpha-dir"},
                        {"id": "beta", "enabled": False},
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_enabled_worlds_and_required_content(self) -> None:
        selection = load_content_selection(self.config, repo_root=self.root)
        self.assertEqual([entry.id for entry in selection.worlds], ["alpha"])
        self.assertEqual(selection.worlds[0].arcname, "worlds/alpha")
        self.assertEqual([entry.id for entry in selection.mods], ["mod-a", "mod-b"])
        self.assertEqual([entry.id for entry in selection.cardsets], ["set-a"])
        self.assertEqual([entry.id for entry in selection.propsets], ["props-a"])

    def test_hash_is_stable_and_changes_with_content(self) -> None:
        first = load_content_selection(self.config, repo_root=self.root)
        second = load_content_selection(self.config, repo_root=self.root)
        self.assertEqual(content_hash(first), content_hash(second))
        _write(self.root / "worlds" / "alpha-dir" / "world.yaml", "id: alpha\nrequires_mods: []\n")
        changed = load_content_selection(self.config, repo_root=self.root)
        self.assertNotEqual(content_hash(first), content_hash(changed))

    def test_release_members_include_only_selected_content(self) -> None:
        selection = load_content_selection(self.config, repo_root=self.root)
        names = {
            arcname.replace("\\", "/")
            for _path, arcname in deploy.release_members(self.root, selection)
        }
        self.assertIn("worlds/alpha/world.yaml", names)
        self.assertIn("mods/mod-a/mod.yaml", names)
        self.assertIn("data/cardsets/set-a/cards.yaml", names)
        self.assertIn("data/propsets/props-a/props.yaml", names)
        self.assertNotIn("worlds/beta/world.yaml", names)
        self.assertNotIn("mods/mod-unused/mod.yaml", names)
        self.assertNotIn("data/cardsets/set-b/cards.yaml", names)
        self.assertNotIn("data/propsets/props-b/props.yaml", names)

    def test_package_name_and_manifest_include_hash(self) -> None:
        selection = load_content_selection(self.config, repo_root=self.root)
        digest = content_hash(selection)
        tarball_name = package_filename("1.2.3", digest)
        self.assertIn(digest, tarball_name)
        self.assertEqual(split_package_stem(f"1.2.3-{digest}"), ("1.2.3", digest))
        releases = self.root / "releases"
        with mock.patch.object(deploy, "REPO_ROOT", self.root), \
                mock.patch.object(deploy, "RELEASES_DIR", releases):
            tarball = deploy.package(
                "1.2.3", False, console=deploy.Console(io.StringIO()),
                selection=selection, version_hash=digest,
            )
        self.assertEqual(tarball.name, tarball_name)
        with tarfile.open(tarball, "r:gz") as archive:
            names = set(archive.getnames())
            manifest = json.loads(archive.extractfile("deploy-manifest.json").read())
        self.assertIn("worlds/alpha/world.yaml", names)
        self.assertNotIn("worlds/beta/world.yaml", names)
        self.assertEqual(manifest["version_hash"], digest)
        self.assertEqual(manifest["worlds"], ["alpha"])
        self.assertEqual(manifest["mods"], ["mod-a", "mod-b"])


class LauncherEnabledTests(unittest.TestCase):
    def test_launcher_skips_disabled_worlds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "fleet.json"
            config.write_text(json.dumps({
                "worlds": [
                    {"id": "alpha", "enabled": True},
                    {"id": "beta", "enabled": False},
                ]
            }), encoding="utf-8")
            loaded = start_multiworld.load_multiworld_config(config)
            self.assertEqual([world.world_id for world in loaded.worlds], ["alpha"])


class DeploymentHashMetadataTests(unittest.TestCase):
    def test_registry_snapshot_carries_version_hash(self) -> None:
        registry = InstanceRegistry()
        record = registry.register({
            "instance_name": "alpha",
            "endpoint": "https://127.0.0.1:5000",
            "instance_id": "alpha-1",
            "version": "1.2.3",
            "version_hash": "abc123",
            "world": {"id": "alpha"},
        })
        self.assertEqual(registry.snapshot(record)["version_hash"], "abc123")

    def test_version_info_reads_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "version.json", json.dumps([{"major": 1, "minor": 2, "patch": 3}]))
            _write(root / "deploy-manifest.json", json.dumps({"version_hash": "abc123"}))
            self.assertEqual(deployment_version_hash(root), "abc123")
            self.assertEqual(version_info(root)["version_hash"], "abc123")
            self.assertEqual(version_info(root)["build"], "1.2.3")


if __name__ == "__main__":
    unittest.main()
