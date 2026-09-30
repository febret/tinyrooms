"""Tests for mission-control nginx configuration generation and application."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest import mock

from starlette.testclient import TestClient

from server.mission_control import nginx as nginx_config
from server.mission_control.app import create_mc_app
from server.mission_control.config import MCConfig, load_mc_config
from server.mission_control.registry import InstanceRegistry
from tests.common import REPO_ROOT
from tests.mc_helpers import MC_BASE_URL, mc_env


def make_config(root: Path) -> MCConfig:
    return load_mc_config(
        env=mc_env(
            root,
            TRSERVER_MC_BASE_PATH="/admin",
            TRSERVER_MC_PUBLIC_ORIGIN="https://tinyrooms.febret.com",
            TRSERVER_MC_NGINX_CONF=str(root / "nginx" / "tinyrooms.conf"),
            TRSERVER_MC_NGINX_RELOAD="reload-me",
        ),
        repo_root=REPO_ROOT,
    )


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = make_config(self.root)

    def test_service_entries_include_admin_and_instances(self) -> None:
        registry = InstanceRegistry()
        registry.register({"instance_name": "Tutorial", "endpoint": "https://127.0.0.1:5099", "base_path": "/tutorial"})
        entries = nginx_config.service_entries(self.config, registry.list())
        routes = {entry["route"] for entry in entries}
        self.assertEqual(routes, {"admin", "tutorial"})
        self.assertEqual(next(entry for entry in entries if entry["route"] == "admin")["port"], 8001)

    def test_render_includes_admin_and_instance_locations(self) -> None:
        registry = InstanceRegistry()
        registry.register({"instance_name": "Tutorial", "endpoint": "https://127.0.0.1:5099", "base_path": "/tutorial"})
        text = nginx_config.render_site_config(self.config, registry.list())
        self.assertIn("server_name tinyrooms.febret.com;", text)
        self.assertIn("location /admin/ {", text)
        self.assertIn("proxy_pass https://127.0.0.1:8001;", text)
        self.assertIn("location /tutorial/ {", text)
        self.assertIn("proxy_pass https://127.0.0.1:5099;", text)
        self.assertIn("ssl_certificate", text)

    def test_route_falls_back_to_instance_id(self) -> None:
        registry = InstanceRegistry()
        record = registry.register({"instance_name": "No Base", "endpoint": "https://127.0.0.1:5098"})
        entries = nginx_config.service_entries(self.config, registry.list())
        self.assertEqual(entries[1]["route"], record.instance_id)

    def test_stopped_instances_are_omitted(self) -> None:
        registry = InstanceRegistry()
        record = registry.register({"instance_name": "Tutorial", "endpoint": "https://127.0.0.1:5099", "base_path": "/tutorial"})
        registry.set_status(record.instance_id, "stopped")
        entries = nginx_config.service_entries(self.config, registry.list())
        self.assertEqual([entry["route"] for entry in entries], ["admin"])


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = make_config(self.root)

    def test_apply_writes_file_and_runs_reload(self) -> None:
        completed = subprocess.CompletedProcess(args=["reload-me"], returncode=0, stdout="reloaded", stderr="")
        with mock.patch.object(nginx_config, "_run_command", return_value=completed) as runner:
            result = nginx_config.apply_site_config(self.config, "server {}\n")
        self.assertEqual(result["path"], str(self.config.nginx_conf_path))
        self.assertIn("reloaded", str(result["output"]))
        self.assertEqual(self.config.nginx_conf_path.read_text(encoding="utf-8"), "server {}\n")
        runner.assert_called_once()

    def test_reload_failure_raises(self) -> None:
        completed = subprocess.CompletedProcess(args=["reload-me"], returncode=1, stdout="", stderr="boom")
        with mock.patch.object(nginx_config, "_run_command", return_value=completed):
            with self.assertRaises(nginx_config.NginxConfigError):
                nginx_config.apply_site_config(self.config, "server {}\n")


class NginxHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = make_config(self.root)
        self.app = create_mc_app(self.config)
        context = TestClient(self.app, base_url=MC_BASE_URL)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.client.post(
            "/api/mission-control/auth/login",
            json={"passphrase": "letmein"},
            headers={"origin": MC_BASE_URL},
        )

    def csrf_headers(self) -> dict[str, str]:
        return {"origin": MC_BASE_URL, "x-csrf-token": self.client.cookies.get("tr_mc_csrf", "")}

    def test_preview_requires_login(self) -> None:
        self.client.post("/api/mission-control/auth/logout", headers=self.csrf_headers())
        response = self.client.get("/api/mission-control/nginx")
        self.assertEqual(response.status_code, 401)

    def test_preview_and_apply_round_trip(self) -> None:
        self.client.post(
            "/api/mc/register",
            json={"instance_name": "Tutorial", "endpoint": "https://127.0.0.1:5099", "base_path": "/tutorial"},
            headers={"x-mc-token": self.config.token},
        )
        preview = self.client.get("/api/mission-control/nginx")
        self.assertEqual(preview.status_code, 200)
        body = preview.json()
        self.assertTrue(body["ok"])
        self.assertIn("location /tutorial/ {", body["config"])

        completed = subprocess.CompletedProcess(args=["reload-me"], returncode=0, stdout="ok", stderr="")
        with mock.patch.object(nginx_config, "_run_command", return_value=completed):
            applied = self.client.post("/api/mission-control/nginx", headers=self.csrf_headers())
        self.assertEqual(applied.status_code, 200)
        self.assertTrue(applied.json()["ok"])
        self.assertTrue(self.config.nginx_conf_path.is_file())


if __name__ == "__main__":
    unittest.main()
