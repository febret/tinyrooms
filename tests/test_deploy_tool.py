"""Tests for the deploy tool's packaging and configuration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import hashlib
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


class _Result:
    """Minimal CompletedProcess stand-in for the mocked remote shell."""

    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


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


class KeepaliveTests(unittest.TestCase):
    def test_script_sources_env_and_tracks_pid(self) -> None:
        script = deploy.keepalive_script("/home/u/.local/tinyrooms")
        self.assertIn('ROOT="/home/u/.local/tinyrooms"', script)
        self.assertIn('ENVFILE="$ROOT/admin.env"', script)
        self.assertIn('. "$ENVFILE"', script)
        self.assertIn('"$ROOT/venv/bin/python" run.py', script)
        self.assertIn('echo $! > "$PIDFILE"', script)

    def test_script_restarts_when_env_changes(self) -> None:
        script = deploy.keepalive_script("/home/u/.local/tinyrooms")
        self.assertIn("env_hash", script)
        self.assertIn('STAMPFILE="$ROOT/admin.env.hash"', script)
        self.assertIn("stop_server", script)
        self.assertIn('echo "$hash" > "$STAMPFILE"', script)

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


class EnvFileRoundTripTests(unittest.TestCase):
    def _read(self, body: str) -> dict[str, str]:
        with mock.patch.object(deploy, "run_remote", return_value=_Result(body)):
            return deploy.read_remote_env("host", "/root")

    def test_every_rendered_value_round_trips(self) -> None:
        secrets = {
            "TRSERVER_MC_PASSPHRASE": "p@ss'word with spaces",
            "TRSERVER_MC_TOKEN": "tok#en;still-one",
            "TRSERVER_MC_NGINX_RELOAD": "sudo -n cp x && systemctl reload nginx",
            "TRSERVER_MC_PUBLIC_ORIGIN": "https://tinyrooms.febret.com",
        }
        parsed = self._read(deploy.render_env_file(secrets))
        for key, value in secrets.items():
            self.assertEqual(parsed[key], value, key)

    def test_accepts_export_prefix_and_trailing_comment(self) -> None:
        parsed = self._read(
            "export TRSERVER_MC_PASSPHRASE='letmein'\n"
            "TRSERVER_MC_TOKEN=plain # operator note\n"
        )
        self.assertEqual(parsed["TRSERVER_MC_PASSPHRASE"], "letmein")
        self.assertEqual(parsed["TRSERVER_MC_TOKEN"], "plain")

    def test_keeps_literal_hash_in_quoted_value(self) -> None:
        parsed = self._read(deploy.render_env_file({"TRSERVER_MC_PASSPHRASE": "a#b"}))
        self.assertEqual(parsed["TRSERVER_MC_PASSPHRASE"], "a#b")


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

    def test_local_environment_overrides_existing_secret(self) -> None:
        values = deploy.admin_env_values(
            "/home/u/.local/tinyrooms",
            "example.com",
            self.REGISTRY,
            {"TRSERVER_MC_PASSPHRASE": "stale", "TRSERVER_MC_TOKEN": "stale"},
            overrides={"TRSERVER_MC_PASSPHRASE": "chosen", "TRSERVER_MC_TOKEN": "shared"},
        )
        self.assertEqual(values["TRSERVER_MC_PASSPHRASE"], "chosen")
        self.assertEqual(values["TRSERVER_MC_TOKEN"], "shared")


class RestartAdminTests(unittest.TestCase):
    def _run(self, pidfile: str) -> list[str]:
        commands: list[str] = []

        def fake_run_remote(host: str, command: str, check: bool = True) -> _Result:
            commands.append(command)
            return _Result(pidfile)

        with mock.patch.object(deploy, "run_remote", side_effect=fake_run_remote), \
                mock.patch.object(deploy.time, "sleep", return_value=None):
            deploy.restart_admin("host", "/root")
        return commands

    def test_stops_tracked_and_untracked_admin_processes(self) -> None:
        commands = self._run("136153\n")
        joined = "\n".join(commands)
        self.assertTrue(any(command.startswith("kill 136153") for command in commands))
        self.assertIn("pkill -f", joined)
        self.assertIn("/root/venv/bin/python run.py", joined)
        self.assertTrue(any("keepalive.sh" in command for command in commands))

    def test_recovers_from_missing_pidfile(self) -> None:
        commands = self._run("")
        joined = "\n".join(commands)
        self.assertNotIn("kill -0", joined)
        self.assertIn("pkill -f", joined)
        self.assertTrue(any("keepalive.sh" in command for command in commands))


class StartScriptTests(unittest.TestCase):
    def test_start_script_sources_admin_env(self) -> None:
        script = (REPO_ROOT / "start.sh").read_text(encoding="utf-8")
        self.assertIn("TRSERVER_ADMIN_ENV", script)
        self.assertIn("admin.env", script)


class UploadTests(unittest.TestCase):
    def test_partial_name_is_content_addressed(self) -> None:
        name = deploy.partial_tarball_name("tinyrooms-1.2.3.tar.gz", "a" * 64)
        self.assertEqual(name, ".tinyrooms-1.2.3.tar.gz.aaaaaaaaaaaa.part")

    def test_partial_name_changes_with_digest(self) -> None:
        first = deploy.partial_tarball_name("tinyrooms-1.2.3.tar.gz", "0" * 64)
        second = deploy.partial_tarball_name("tinyrooms-1.2.3.tar.gz", "1" * 64)
        self.assertNotEqual(first, second)

    def test_local_sha256_matches_hashlib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            payload = b"tinyrooms" * 4096
            path.write_bytes(payload)
            self.assertEqual(deploy.local_sha256(path), hashlib.sha256(payload).hexdigest())


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
