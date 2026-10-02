"""Mission-control Server Info metrics, storage, and install-root tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest

from starlette.testclient import TestClient

from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from server.version import BUILD_VERSION
from tests.common import REPO_ROOT
from tests.mc_helpers import MC_BASE_URL, McHttpTestCase, mc_env


class ServerInfoRouteTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()

    def test_requires_authentication(self) -> None:
        anonymous_context = TestClient(self.app, base_url=MC_BASE_URL)
        anonymous = anonymous_context.__enter__()
        self.addCleanup(anonymous_context.__exit__, None, None, None)
        self.assertEqual(anonymous.get("/api/mission-control/server").status_code, 401)
        self.assertEqual(anonymous.get("/api/mission-control/server/storage").status_code, 401)

    def test_snapshot_shape_and_no_secrets(self) -> None:
        payload = self.client.get("/api/mission-control/server").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["process"]["pid"], os.getpid())
        self.assertGreaterEqual(payload["process"]["uptime_seconds"], 0)
        self.assertTrue(payload["host"]["hostname"])
        self.assertEqual(payload["config"]["version"], BUILD_VERSION)
        self.assertIsNotNone(payload["disk"])
        self.assertGreater(payload["disk"]["total"], 0)
        serialized = json.dumps(payload)
        self.assertNotIn(self.config.token, serialized)
        self.assertNotIn(self.config.passphrase, serialized)


class ServerInfoStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.install = root / "install"
        (self.install / "alpha").mkdir(parents=True)
        (self.install / "alpha" / "a.bin").write_bytes(b"x" * 100)
        (self.install / "beta").mkdir()
        (self.install / "beta" / "b.bin").write_bytes(b"y" * 50)
        (self.install / "loose.bin").write_bytes(b"z" * 10)

        config = load_mc_config(
            env=mc_env(root, TRSERVER_MC_INSTALL_PATH=str(self.install)),
            repo_root=REPO_ROOT,
        )
        app = create_mc_app(config)
        self.context = TestClient(app, base_url=MC_BASE_URL)
        self.client = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.client.post(
            "/api/mission-control/auth/login",
            json={"passphrase": "letmein"},
            headers={"origin": MC_BASE_URL},
        )

    def test_storage_breakdown(self) -> None:
        payload = self.client.get("/api/mission-control/server/storage").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path"], str(self.install))
        self.assertEqual(payload["total"], 160)
        sizes = {entry["name"]: entry["size"] for entry in payload["entries"]}
        self.assertEqual(sizes["alpha"], 100)
        self.assertEqual(sizes["beta"], 50)
        self.assertEqual(sizes["loose.bin"], 10)

    def test_storage_cache_and_refresh(self) -> None:
        self.assertEqual(self.client.get("/api/mission-control/server/storage").json()["total"], 160)
        (self.install / "beta" / "b.bin").write_bytes(b"y" * 90)
        cached = self.client.get("/api/mission-control/server/storage").json()
        self.assertEqual(cached["total"], 160)
        refreshed = self.client.get("/api/mission-control/server/storage?refresh=1").json()
        self.assertEqual(refreshed["total"], 200)


class InstallRootDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_production_deploy_uses_content_root(self) -> None:
        versions = self.root / "versions"
        repo = versions / "1.0.0"
        repo.mkdir(parents=True)
        config = load_mc_config(
            env=mc_env(self.root, TSRVER_MC_VERSIONS_PATH=str(versions)),
            repo_root=repo,
        )
        self.assertEqual(config.content_root.resolve(), self.root.resolve())
        self.assertEqual(config.install_root.resolve(), self.root.resolve())

    def test_local_dev_uses_repo_root(self) -> None:
        repo = self.root / "repo"
        repo.mkdir()
        config = load_mc_config(
            env=mc_env(repo, TSRVER_MC_VERSIONS_PATH=str(repo / ".local" / "mc-versions")),
            repo_root=repo,
        )
        self.assertEqual(config.install_root.resolve(), repo.resolve())

    def test_explicit_override(self) -> None:
        target = self.root / "custom"
        target.mkdir()
        config = load_mc_config(
            env=mc_env(self.root, TRSERVER_MC_INSTALL_PATH=str(target)),
            repo_root=self.root,
        )
        self.assertEqual(config.install_root, target)


if __name__ == "__main__":
    unittest.main()
