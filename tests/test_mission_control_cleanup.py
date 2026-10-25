"""Mission-control bulk release-cleanup and nginx-refresh tests."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest

from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from server.mission_control.world_map import WorldMapManager
from tests.common import REPO_ROOT
from tests.mc_helpers import MC_BASE_URL, McHttpTestCase, mc_env


def _make_version(root: Path, version_id: str) -> Path:
    candidate = root / "versions" / version_id
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "run.py").write_text("# test checkout\n", encoding="utf-8")
    return candidate


def _make_tarball(root: Path, version_id: str, size: int = 64) -> Path:
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    tarball = releases / f"tinyrooms-{version_id}.tar.gz"
    tarball.write_bytes(b"x" * size)
    return tarball


class CleanupCandidatesTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.app.state.mc

    def register_versioned(self, version: str) -> str:
        response = self.client.post(
            "/api/mc/register",
            json={
                "instance_name": "versioned",
                "endpoint": "https://127.0.0.1:59998",
                "base_path": "/versioned",
                "version": version,
                "world": {"id": "tutorial"},
            },
            headers={"x-mc-token": self.config.token},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["instance_id"]

    def test_unused_checkout_and_orphan_tarball_are_candidates(self) -> None:
        _make_version(self.root, "old1")
        _make_tarball(self.root, "old1")
        _make_version(self.root, "used1")
        _make_tarball(self.root, "ghost")
        self.register_versioned("used1")

        candidates = self.runtime.packages.cleanup_candidates()
        by_id = {item["id"]: item for item in candidates}
        self.assertIn("old1", by_id)
        self.assertEqual(by_id["old1"]["kind"], "version")
        self.assertIn("ghost", by_id)
        self.assertEqual(by_id["ghost"]["kind"], "tarball")
        self.assertNotIn("used1", by_id)

    def test_used_checkout_never_candidate(self) -> None:
        _make_version(self.root, "used2")
        self.register_versioned("used2")
        by_id = {item["id"]: item for item in self.runtime.packages.cleanup_candidates()}
        self.assertNotIn("used2", by_id)

    def test_latest_target_protected(self) -> None:
        target = _make_version(self.root, "keep")
        latest = self.root / "versions" / "latest"
        try:
            os.symlink(target, latest, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are unavailable")
        by_id = {item["id"]: item for item in self.runtime.packages.cleanup_candidates()}
        self.assertNotIn("keep", by_id)
        with self.assertRaises(ValueError):
            self.runtime.packages.delete_version("keep", actor="operator")

    def test_latest_target_protected_via_resolved_target(self) -> None:
        from unittest import mock

        _make_version(self.root, "pinned")
        pinned = self.root / "versions" / "pinned"
        with mock.patch.object(
            type(self.runtime.packages), "_latest_target", lambda _self: pinned.resolve()
        ):
            by_id = {item["id"]: item for item in self.runtime.packages.cleanup_candidates()}
            self.assertNotIn("pinned", by_id)
            with self.assertRaises(ValueError):
                self.runtime.packages.delete_version("pinned", actor="operator")

    def test_cleanup_deletes_selected_and_frees_bytes(self) -> None:
        _make_version(self.root, "old2")
        _make_tarball(self.root, "old2", size=128)
        _make_tarball(self.root, "ghost2", size=64)

        result = self.runtime.packages.cleanup_versions(["old2", "ghost2"], actor="operator")
        self.assertEqual(sorted(result["deleted"]), ["ghost2", "old2"])
        self.assertEqual(result["failed"], [])
        self.assertGreater(int(result["freed_bytes"]), 0)
        self.assertFalse((self.root / "versions" / "old2").exists())
        self.assertFalse((self.root / "releases" / "tinyrooms-old2.tar.gz").exists())
        self.assertFalse((self.root / "releases" / "tinyrooms-ghost2.tar.gz").exists())
        actions = [entry["action"] for entry in self.runtime.audit.entries(50)]
        self.assertIn("version.delete", actions)

    def test_cleanup_unknown_id_fails(self) -> None:
        result = self.runtime.packages.cleanup_versions(["nope"], actor="operator")
        self.assertEqual(result["deleted"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["code"], "unknown_candidate")

    def test_cleanup_skips_used_version_registered_after_preview(self) -> None:
        _make_version(self.root, "racy")
        self.register_versioned("racy")
        result = self.runtime.packages.cleanup_versions(["racy"], actor="operator")
        self.assertEqual(result["deleted"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertTrue((self.root / "versions" / "racy").is_dir())


class CleanupRouteTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.app.state.mc

    def test_cleanup_requires_operator(self) -> None:
        from starlette.testclient import TestClient

        with TestClient(self.app, base_url=MC_BASE_URL) as anonymous:
            response = anonymous.post("/api/mission-control/versions/cleanup", json={"dry_run": True})
        self.assertEqual(response.status_code, 401)

    def test_cleanup_dry_run_then_delete(self) -> None:
        _make_version(self.root, "old3")
        _make_tarball(self.root, "orphan3", size=32)

        preview = self.client.post(
            "/api/mission-control/versions/cleanup",
            json={"dry_run": True},
            headers=self.csrf_headers(),
        )
        self.assertEqual(preview.status_code, 200)
        ids = {item["id"] for item in preview.json()["candidates"]}
        self.assertTrue({"old3", "orphan3"} <= ids)

        deleted = self.client.post(
            "/api/mission-control/versions/cleanup",
            json={"ids": ["old3", "orphan3"]},
            headers=self.csrf_headers(),
        )
        self.assertEqual(deleted.status_code, 200)
        payload = deleted.json()
        self.assertEqual(sorted(payload["deleted"]), ["old3", "orphan3"])
        self.assertEqual(payload["failed"], [])


class NginxRefreshRouteTests(McHttpTestCase):
    def _enabled_app(self):
        target = Path(self.temporary_directory.name) / "nginx" / "tinyrooms-worlds.map"
        target.parent.mkdir(parents=True, exist_ok=True)
        config = load_mc_config(
            env=mc_env(
                Path(self.temporary_directory.name),
                TRSERVER_MC_SAME_ORIGIN_WORLDS="1",
                TRSERVER_MC_WORLD_MAP=str(target),
                TRSERVER_MC_WORLD_MAP_RELOAD="true",
            ),
            repo_root=REPO_ROOT,
        )
        return create_mc_app(config), target

    def test_refresh_unconfigured(self) -> None:
        self.login()
        response = self.client.post("/api/mission-control/nginx/refresh", json={}, headers=self.csrf_headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "nginx_unconfigured")

    def test_refresh_requires_operator(self) -> None:
        from starlette.testclient import TestClient

        with TestClient(self.app, base_url=MC_BASE_URL) as anonymous:
            response = anonymous.post("/api/mission-control/nginx/refresh", json={})
        self.assertEqual(response.status_code, 401)

    def test_refresh_reports_routed_and_audits(self) -> None:
        from starlette.testclient import TestClient

        app, target = self._enabled_app()
        with TestClient(app, base_url=MC_BASE_URL) as client:
            client.post("/api/mission-control/auth/login", json={"passphrase": "letmein"}, headers={"origin": MC_BASE_URL})
            csrf = client.cookies.get("tr_mc_csrf", "")
            runtime = app.state.mc
            record = runtime.registry.register_spawned(
                instance_id="mc-one",
                name="mc-one",
                endpoint="https://127.0.0.1:10000",
                instance_dir=str(Path(self.temporary_directory.name) / "mc-one"),
                process_handle=None,
                spawn_config={"port": 10000, "base_path": "/world/mc-one"},
                base_path="/world/mc-one",
            )
            runtime.registry.set_status(record.instance_id, "running")

            def runner(command: object, *, shell: bool = False) -> None:
                if isinstance(command, list) and command[:3] == ["sudo", "-n", "install"]:
                    shutil.copyfile(command[-2], command[-1])

            runtime.world_map._runner = runner
            first = client.post(
                "/api/mission-control/nginx/refresh",
                json={},
                headers={"origin": MC_BASE_URL, "x-csrf-token": csrf},
            )
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["ok"])
            self.assertEqual(first.json()["routed"], 1)
            self.assertTrue(first.json()["changed"])
            self.assertIn('mc-one "https://127.0.0.1:10000";', target.read_text(encoding="utf-8"))

            second = client.post(
                "/api/mission-control/nginx/refresh",
                json={},
                headers={"origin": MC_BASE_URL, "x-csrf-token": csrf},
            )
            self.assertEqual(second.json()["changed"], False)
            actions = [entry["action"] for entry in runtime.audit.entries(50)]
            self.assertIn("nginx.refresh", actions)


class WorldMapForceTests(unittest.TestCase):
    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.target = self.root / "nginx" / "tinyrooms-worlds.map"
        self.target.parent.mkdir(parents=True)
        self.config = load_mc_config(
            env=mc_env(
                self.root,
                TRSERVER_MC_SAME_ORIGIN_WORLDS="1",
                TRSERVER_MC_WORLD_MAP=str(self.target),
                TRSERVER_MC_WORLD_MAP_RELOAD="true",
            ),
            repo_root=REPO_ROOT,
        )
        from server.mission_control.registry import STATUS_RUNNING, InstanceRegistry

        self.registry = InstanceRegistry()
        record = self.registry.register_spawned(
            instance_id="mc-one",
            name="mc-one",
            endpoint="https://127.0.0.1:10000",
            instance_dir=str(self.root / "mc-one"),
            process_handle=None,
            spawn_config={"port": 10000, "base_path": "/world/mc-one"},
            base_path="/world/mc-one",
        )
        self.registry.set_status(record.instance_id, STATUS_RUNNING)
        self.installs = 0

    def _runner(self, command: object, *, shell: bool = False) -> None:
        if isinstance(command, list) and command[:3] == ["sudo", "-n", "install"]:
            self.installs += 1
            shutil.copyfile(command[-2], command[-1])

    def test_force_reinstalls_when_unchanged(self) -> None:
        manager = WorldMapManager(self.config, self.registry, command_runner=self._runner)
        first = manager.update()
        self.assertTrue(first["changed"])
        self.assertEqual(first["routed"], 1)
        second = manager.update()
        self.assertFalse(second["changed"])
        self.assertEqual(self.installs, 1)
        third = manager.update(force=True)
        self.assertFalse(third["changed"])
        self.assertEqual(third["routed"], 1)
        self.assertEqual(self.installs, 2)


if __name__ == "__main__":
    unittest.main()
