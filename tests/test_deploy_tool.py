"""Tests for the deploy tool's packaging and configuration helpers."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import tarfile
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deploy_tool", REPO_ROOT / "tools" / "deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deploy)


class RemotePathTests(unittest.TestCase):
    def test_joins_absolute_root(self) -> None:
        self.assertEqual(
            deploy.remote_path("/home/u/.local/tinyrooms", "versions", "latest"),
            "/home/u/.local/tinyrooms/versions/latest",
        )


class ResolveTargetTests(unittest.TestCase):
    def test_bare_host_without_user(self) -> None:
        self.assertEqual(deploy.resolve_target("example.com", None), ("example.com", "example.com"))

    def test_user_flag_applied(self) -> None:
        self.assertEqual(deploy.resolve_target("example.com", "febret"), ("febret@example.com", "example.com"))

    def test_user_in_host_spec(self) -> None:
        self.assertEqual(deploy.resolve_target("febret@example.com", None), ("febret@example.com", "example.com"))

    def test_user_flag_overrides_host_spec(self) -> None:
        self.assertEqual(deploy.resolve_target("other@example.com", "febret"), ("febret@example.com", "example.com"))


class VersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.version_file = Path(self._tmp.name) / "version.json"
        self._original = deploy.VERSION_FILE
        deploy.VERSION_FILE = self.version_file

    def tearDown(self) -> None:
        deploy.VERSION_FILE = self._original
        self._tmp.cleanup()

    def test_patch_increments(self) -> None:
        label, dirty = deploy.bump_version(False)
        self.assertEqual((label, dirty), ("0.0.1", False))
        label, _ = deploy.bump_version(False)
        self.assertEqual(label, "0.0.2")
        entries = json.loads(self.version_file.read_text(encoding="utf-8"))
        self.assertEqual(entries[-1]["patch"], 2)

    def test_dirty_entry_tagged(self) -> None:
        deploy.bump_version(True)
        entries = json.loads(self.version_file.read_text(encoding="utf-8"))
        self.assertIs(entries[-1]["dirty"], True)

    def test_latest_uses_numeric_ordering(self) -> None:
        entries = [
            {"major": 0, "minor": 2, "patch": 0},
            {"major": 0, "minor": 10, "patch": 1},
            {"major": 1, "minor": 0, "patch": 0},
        ]
        self.assertEqual(deploy.latest_version(entries)["minor"], 0)
        self.assertEqual(deploy.latest_version(entries)["major"], 1)

    def test_current_version_returns_latest_without_writing(self) -> None:
        entries = [
            {"major": 0, "minor": 0, "patch": 2},
            {"major": 0, "minor": 3, "patch": 4},
        ]
        self.version_file.write_text(json.dumps(entries), encoding="utf-8")
        before = self.version_file.read_text(encoding="utf-8")
        self.assertEqual(deploy.current_version(), "0.3.4")
        self.assertEqual(self.version_file.read_text(encoding="utf-8"), before)

    def test_current_version_requires_entries(self) -> None:
        with self.assertRaises(deploy.DeployError):
            deploy.current_version()


class ParseArgsTests(unittest.TestCase):
    def test_keep_version_flag(self) -> None:
        args = deploy.parse_args(["example.com", "~/.local/tinyrooms", "deploy", "--keep-version"])
        self.assertTrue(args.keep_version)

    def test_keep_version_defaults_off(self) -> None:
        args = deploy.parse_args(["example.com"])
        self.assertFalse(args.keep_version)


class NginxTests(unittest.TestCase):
    def test_locations_generated_per_service(self) -> None:
        registry = {"admin": {"port": 8123}}
        locations = deploy.nginx_locations(registry)
        self.assertIn("location /admin/ {", locations)
        self.assertIn("proxy_pass https://127.0.0.1:8123;", locations)
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", locations)

    def test_config_references_certificate(self) -> None:
        registry = {"admin": {"port": 8123}}
        config = deploy.nginx_config("tinyrooms.febret.com", "/home/u/.local/tinyrooms", registry)
        self.assertIn("server_name tinyrooms.febret.com;", config)
        self.assertIn("ssl_certificate /home/u/.local/tinyrooms/nginx/certs/server.crt;", config)
        self.assertIn("return 301 https://$host$request_uri;", config)


class KeepaliveTests(unittest.TestCase):
    def test_script_sources_env_and_tracks_pid(self) -> None:
        script = deploy.keepalive_script("/home/u/.local/tinyrooms")
        self.assertIn('ROOT="/home/u/.local/tinyrooms"', script)
        self.assertIn('. "$ROOT/admin.env"', script)
        self.assertIn('"$ROOT/venv/bin/python" run.py', script)
        self.assertIn('echo $! > "$PIDFILE"', script)

    def test_cron_entries_cover_reboot_and_periodic_supervision(self) -> None:
        entries = deploy.keepalive_cron_entries("/home/u/.local/tinyrooms")
        self.assertIn("@reboot /home/u/.local/tinyrooms/keepalive.sh", entries)
        self.assertIn("* * * * * /home/u/.local/tinyrooms/keepalive.sh", entries)


class EnvFileTests(unittest.TestCase):
    def test_commands_with_spaces_are_quoted(self) -> None:
        body = deploy.render_env_file({"TRSERVER_MC_NGINX_RELOAD": "sudo -n cp x && echo hi"})
        self.assertEqual(body, "TRSERVER_MC_NGINX_RELOAD='sudo -n cp x && echo hi'\n")

    def test_plain_values_stay_unquoted(self) -> None:
        body = deploy.render_env_file({"TRSERVER_FEATURES": "mission-control"})
        self.assertEqual(body, "TRSERVER_FEATURES=mission-control\n")


class AdminEnvTests(unittest.TestCase):
    REGISTRY = {"admin": {"port": 8001}}

    def test_preserves_new_account_passphrase_when_set(self) -> None:
        values = deploy.admin_env_values(
            "/home/u/.local/tinyrooms",
            "example.com",
            self.REGISTRY,
            {"TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE": "choose-an-invitation"},
        )
        self.assertEqual(values["TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE"], "choose-an-invitation")

    def test_omits_new_account_passphrase_when_unset(self) -> None:
        values = deploy.admin_env_values("/home/u/.local/tinyrooms", "example.com", self.REGISTRY, {})
        self.assertNotIn("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE", values)

    def test_preserves_operator_secrets(self) -> None:
        values = deploy.admin_env_values(
            "/home/u/.local/tinyrooms",
            "example.com",
            self.REGISTRY,
            {"TRSERVER_MC_PASSPHRASE": "operator-passphrase", "TRSERVER_MC_TOKEN": "shared-secret"},
        )
        self.assertEqual(values["TRSERVER_MC_PASSPHRASE"], "operator-passphrase")
        self.assertEqual(values["TRSERVER_MC_TOKEN"], "shared-secret")


class PackageTests(unittest.TestCase):
    def test_package_excludes_development_directories(self) -> None:
        original_root = deploy.REPO_ROOT
        original_releases = deploy.RELEASES_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server").mkdir()
            (root / "server" / "app.py").write_text("print('ok')", encoding="utf-8")
            (root / "version.json").write_text("[]", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "junk.js").write_text("junk", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "pyvenv.cfg").write_text("home=.", encoding="utf-8")
            (root / "state.sqlite3").write_text("db", encoding="utf-8")
            deploy.REPO_ROOT = root
            deploy.RELEASES_DIR = root / "releases"
            try:
                tarball = deploy.package("1.2.3", False)
                with tarfile.open(tarball, "r:gz") as archive:
                    names = archive.getnames()
            finally:
                deploy.REPO_ROOT = original_root
                deploy.RELEASES_DIR = original_releases
        self.assertIn("server/app.py", names)
        self.assertIn("version.json", names)
        self.assertNotIn("node_modules/junk.js", names)
        self.assertNotIn(".venv/pyvenv.cfg", names)
        self.assertNotIn("state.sqlite3", names)


if __name__ == "__main__":
    unittest.main()
