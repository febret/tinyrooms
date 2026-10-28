"""Tests for the deploy tool's console output and force-restart wiring."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deploy_tool", REPO_ROOT / "tools" / "deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)


class ParseArgsTests(unittest.TestCase):
    def test_force_restart_flag(self) -> None:
        for flag in ("--force-restart", "--forcerestart"):
            with self.subTest(flag=flag):
                args = deploy.parse_args(["example.com", "~/tinyrooms", flag])
                self.assertTrue(args.force_restart)

    def test_force_restart_defaults_off(self) -> None:
        args = deploy.parse_args(["example.com"])
        self.assertFalse(args.force_restart)

    def test_content_flag(self) -> None:
        args = deploy.parse_args(["example.com", "--content", "fleet.json"])
        self.assertEqual(args.content, Path("fleet.json"))
        self.assertEqual(deploy.parse_args(["example.com"]).content.name, "multiworld.json")

    def test_force_flag(self) -> None:
        args = deploy.parse_args(["example.com", "--force"])
        self.assertTrue(args.force)

    def test_force_defaults_off(self) -> None:
        args = deploy.parse_args(["example.com"])
        self.assertFalse(args.force)

    def test_keep_version_flag_is_gone(self) -> None:
        with self.assertRaises(SystemExit):
            deploy.parse_args(["example.com", "--keep-version"])


class CurrentVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._original = deploy.VERSION_FILE
        deploy.VERSION_FILE = Path(self._tmp.name) / "version.json"

    def tearDown(self) -> None:
        deploy.VERSION_FILE = self._original

    def test_returns_newest_recorded_version_without_writing(self) -> None:
        entries = [
            {"major": 0, "minor": 0, "patch": 2},
            {"major": 0, "minor": 3, "patch": 4},
            {"major": 0, "minor": 1, "patch": 9},
        ]
        deploy.VERSION_FILE.write_text(json.dumps(entries), encoding="utf-8")
        before = deploy.VERSION_FILE.read_text(encoding="utf-8")
        self.assertEqual(deploy.current_version(), "0.3.4")
        self.assertEqual(deploy.VERSION_FILE.read_text(encoding="utf-8"), before)

    def test_requires_entries(self) -> None:
        deploy.VERSION_FILE.write_text("[]", encoding="utf-8")
        with self.assertRaises(deploy.DeployError):
            deploy.current_version()


class ConsoleTests(unittest.TestCase):
    def test_plain_mode_has_no_color_or_carriage_returns(self) -> None:
        stream = io.StringIO()
        console = deploy.Console(stream, color=False, animated=False)
        console.phase(1, 3, "Verifying working tree")
        console.success("Remote tooling ready")
        console.warning("Skipped legacy: external")
        console.error("Fleet restart failed")
        output = stream.getvalue()
        self.assertNotIn("\x1b[", output)
        self.assertNotIn("\r", output)
        self.assertIn("[1/3]", output)
        self.assertIn("Remote tooling ready", output)

    def test_color_mode_emits_ansi(self) -> None:
        stream = io.StringIO()
        console = deploy.Console(stream, color=True, animated=False)
        console.phase(2, 3, "Packaging release")
        console.success("Done")
        output = stream.getvalue()
        self.assertIn("\x1b[", output)

    def test_progress_plain_mode_reports_milestones(self) -> None:
        stream = io.StringIO()
        console = deploy.Console(stream, color=False, animated=False)
        with console.progress("Uploading tinyrooms-1.tar.gz", 100) as advance:
            advance(25)
            advance(25)
            advance(50)
        output = stream.getvalue()
        self.assertIn("25%", output)
        self.assertIn("100%", output)

    def test_progress_animated_renders_bar(self) -> None:
        stream = io.StringIO()
        console = deploy.Console(stream, color=False, animated=True)
        with console.progress("Uploading tinyrooms-1.tar.gz", 100) as advance:
            advance(50)
        output = stream.getvalue()
        self.assertIn("50%", output)
        self.assertIn("Uploading tinyrooms-1.tar.gz", output)

    def test_spinner_plain_mode_prints_pending_and_done_lines(self) -> None:
        stream = io.StringIO()
        console = deploy.Console(stream, color=False, animated=False)
        with console.spinner("Checking remote prerequisites", "Remote tooling ready"):
            pass
        output = stream.getvalue()
        self.assertIn("Checking remote prerequisites ...", output)
        self.assertIn("Remote tooling ready", output)


class FleetEventTests(unittest.TestCase):
    def _console(self) -> tuple[deploy.Console, io.StringIO]:
        stream = io.StringIO()
        return deploy.Console(stream, color=False, animated=False), stream

    def test_successful_roll_renders_per_instance_status(self) -> None:
        console, stream = self._console()
        lines = [
            json.dumps({"type": "begin", "version": "0.4.2", "total": 1, "skipped": []}),
            json.dumps({"type": "instance", "instance_id": "a", "name": "Tiny Town",
                        "world": "tinytown", "status": "updating"}),
            json.dumps({"type": "instance", "instance_id": "a", "name": "Tiny Town",
                        "world": "tinytown", "status": "waiting"}),
            json.dumps({"type": "instance", "instance_id": "a", "name": "Tiny Town",
                        "world": "tinytown", "status": "ready", "elapsed": 3.1}),
            json.dumps({"type": "done", "updated": 1, "skipped": 0, "failed": 0, "failures": []}),
        ]
        failures = deploy.render_fleet_events("0.4.2", lines, console=console)
        output = stream.getvalue()
        self.assertEqual(failures, [])
        self.assertIn("Rolling 1 running instance(s) to version 0.4.2", output)
        self.assertIn("Restarted Tiny Town (tinytown) on 0.4.2", output)

    def test_failures_and_skips_are_reported(self) -> None:
        console, stream = self._console()
        lines = [
            json.dumps({"type": "begin", "version": "0.4.2", "total": 1, "skipped": [
                {"instance_id": "x", "name": "Legacy", "reason": "external instance"},
            ]}),
            json.dumps({"type": "instance", "instance_id": "a", "name": "Tiny Town",
                        "world": "tinytown", "status": "updating"}),
            json.dumps({"type": "instance", "instance_id": "a", "name": "Tiny Town",
                        "world": "tinytown", "status": "failed", "message": "boom"}),
            json.dumps({"type": "done", "updated": 0, "skipped": 1, "failed": 1, "failures": ["Tiny Town"]}),
        ]
        failures = deploy.render_fleet_events("0.4.2", lines, console=console)
        output = stream.getvalue()
        self.assertEqual(failures, ["Tiny Town (tinytown)"])
        self.assertIn("Skipped Legacy", output)
        self.assertIn("Failed to restart Tiny Town", output)

    def test_non_json_lines_become_warnings(self) -> None:
        console, stream = self._console()
        failures = deploy.render_fleet_events("0.4.2", ["some ssh noise"], console=console)
        self.assertEqual(failures, [])
        self.assertIn("some ssh noise", stream.getvalue())


class ForceRestartFleetTests(unittest.TestCase):
    def test_fresh_install_skips_without_ssh_helper(self) -> None:
        with mock.patch.object(deploy, "run_remote") as run_remote:
            run_remote.return_value = mock.Mock(returncode=1)
            console = deploy.Console(io.StringIO(), color=False, animated=False)
            failures = deploy.force_restart_fleet("host", "/root", "0.4.2", console=console)
        self.assertEqual(failures, [])
        run_remote.assert_called_once()

    def test_unreachable_mc_warns_and_continues(self) -> None:
        with mock.patch.object(deploy, "run_remote") as run_remote, \
                mock.patch.object(deploy, "stream_remote", return_value=2) as stream_remote:
            run_remote.return_value = mock.Mock(returncode=0)
            stream = io.StringIO()
            console = deploy.Console(stream, color=False, animated=False)
            failures = deploy.force_restart_fleet("host", "/root", "0.4.2", console=console)
        self.assertEqual(failures, [])
        self.assertTrue(stream_remote.called)
        self.assertIn("not reachable", stream.getvalue())

    def test_helper_error_raises_deploy_error(self) -> None:
        with mock.patch.object(deploy, "run_remote") as run_remote, \
                mock.patch.object(deploy, "stream_remote") as stream_remote:
            run_remote.return_value = mock.Mock(returncode=0)

            def fake_stream(host: str, command: str, on_line) -> int:
                on_line(json.dumps({"type": "error", "message": "bad passphrase"}))
                return 3

            stream_remote.side_effect = fake_stream
            console = deploy.Console(io.StringIO(), color=False, animated=False)
            with self.assertRaises(deploy.DeployError):
                deploy.force_restart_fleet("host", "/root", "0.4.2", console=console)


class PackageTests(unittest.TestCase):
    def _make_tree(self, root: Path) -> None:
        runtime = [
            "run.py", "version.json", "requirements.txt", "README.md",
            "server/app.py", "client/app.js", "data/core/x.yaml",
            "worlds/w/world.yaml", "mods/m/m.py", "tools/fleet_restart.py",
        ]
        for item in runtime:
            path = root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        excluded = [
            "doc/guide.md", "doc/slides.pptx", "tests/test_x.py",
            "AGENTS.md", "TASKS.md", ".gitignore", "playwright.config.js",
            "playwright.perf.config.js", "requirements-dev.txt", "run_tests.sh",
            ".venv/x.py", "node_modules/y.js", "attic/z.txt", "releases/old.tar.gz",
            "server/__pycache__/a.pyc", "server/worldstate.db",
        ]
        for item in excluded:
            path = root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def test_release_members_keep_runtime_and_drop_dev_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_tree(root)
            names = {arcname.replace("\\", "/") for _, arcname in deploy.release_members(root)}
        for kept in ("run.py", "version.json", "requirements.txt",
                     "server/app.py", "client/app.js", "data/core/x.yaml",
                     "worlds/w/world.yaml", "mods/m/m.py",
                     "tools/fleet_restart.py"):
            self.assertIn(kept, names)
        for dropped in ("doc/guide.md", "doc/slides.pptx", "tests/test_x.py",
                        "AGENTS.md", "TASKS.md", ".gitignore",
                        "playwright.config.js", "playwright.perf.config.js",
                        "requirements-dev.txt", "run_tests.sh",
                        ".venv/x.py", "node_modules/y.js", "attic/z.txt",
                        "releases/old.tar.gz", "server/__pycache__/a.pyc",
                        "server/worldstate.db"):
            self.assertNotIn(dropped, names)
        self.assertNotIn("releases", [name.split("/")[0] for name in names])


class ArtifactGuardTests(unittest.TestCase):
    def test_local_clash_detects_existing_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            releases = Path(tmp)
            (releases / "tinyrooms-9.9.9.tar.gz").write_text("x", encoding="utf-8")
            clashes = deploy.local_artifact_clashes("9.9.9", releases_dir=releases)
        self.assertEqual(len(clashes), 1)
        self.assertIn("9.9.9", clashes[0])

    def test_local_clash_empty_without_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(deploy.local_artifact_clashes("9.9.9", releases_dir=Path(tmp)), [])

    def test_remote_clashes_report_tarball_and_checkout(self) -> None:
        calls: list[str] = []

        def fake_run_remote(host: str, command: str, **kwargs: object) -> mock.Mock:
            calls.append(command)
            result = mock.Mock()
            result.returncode = 0 if "releases" not in command else 1
            return result

        with mock.patch.object(deploy, "run_remote", side_effect=fake_run_remote):
            clashes = deploy.remote_artifact_clashes("host", "/srv/tiny", "9.9.9")
        self.assertEqual(len(clashes), 1)
        self.assertIn("checkout", clashes[0])
        self.assertIn("9.9.9", clashes[0])
        self.assertEqual(len(calls), 2)

    def test_remote_clashes_empty_when_nothing_exists(self) -> None:
        result = mock.Mock()
        result.returncode = 1
        with mock.patch.object(deploy, "run_remote", return_value=result):
            self.assertEqual(deploy.remote_artifact_clashes("host", "/srv/tiny", "9.9.9"), [])

    def _run_deploy(self, *, force: bool, local_tarball: bool,
                    remote_tarball: bool, remote_dir: bool) -> mock.Mock:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        releases = Path(tmp.name)
        if local_tarball:
            (releases / "tinyrooms-9.9.9.tar.gz").write_text("x", encoding="utf-8")
        stream = io.StringIO()
        console = deploy.Console(stream, color=False, animated=False)

        def fake_run_remote(host: str, command: str, **kwargs: object) -> mock.Mock:
            result = mock.Mock()
            result.stdout = ""
            result.stderr = ""
            if "test -e" in command:
                if "releases" in command:
                    result.returncode = 0 if remote_tarball else 1
                else:
                    result.returncode = 0 if remote_dir else 1
            else:
                result.returncode = 0
            return result

        patches = [
            mock.patch.object(deploy, "RELEASES_DIR", releases),
            mock.patch.object(deploy, "git_dirty", return_value=False),
            mock.patch.object(deploy, "check_remote_prerequisites"),
            mock.patch.object(deploy, "ensure_dirs"),
            mock.patch.object(deploy, "ensure_python_env"),
            mock.patch.object(deploy, "write_services", return_value={
                "admin": {"port": "8001", "base_path": "", "feature": "mission-control"}}),
            mock.patch.object(deploy, "ensure_nginx"),
            mock.patch.object(deploy, "current_version", return_value="9.9.9"),
            mock.patch.object(
                deploy,
                "load_content_selection",
                return_value=deploy.ContentSelection((), (), (), ()),
            ),
            mock.patch.object(deploy, "run_remote", side_effect=fake_run_remote),
            mock.patch.object(deploy, "package", return_value=releases / "tinyrooms-9.9.9.tar.gz"),
            mock.patch.object(deploy, "install_requirements"),
            mock.patch.object(deploy, "write_admin_env"),
            mock.patch.object(deploy, "ensure_keepalive"),
            mock.patch.object(deploy, "restart_admin"),
            mock.patch.object(deploy, "wait_for_admin"),
        ]
        upload_patcher = mock.patch.object(deploy, "upload_release")
        upload_release = upload_patcher.start()
        self.addCleanup(upload_patcher.stop)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return upload_release, deploy.deploy(
            "host", "example.com", "/srv/tiny", False, force=force, console=console)

    def test_deploy_errors_on_local_clash_without_force(self) -> None:
        with self.assertRaises(deploy.DeployError) as raised:
            self._run_deploy(force=False, local_tarball=True, remote_tarball=False, remote_dir=False)
        self.assertIn("9.9.9", str(raised.exception))
        self.assertIn("--force", str(raised.exception))

    def test_deploy_errors_on_remote_clash_without_force(self) -> None:
        with self.assertRaises(deploy.DeployError) as raised:
            self._run_deploy(force=False, local_tarball=False, remote_tarball=True, remote_dir=True)
        message = str(raised.exception)
        self.assertIn("9.9.9", message)
        self.assertIn("remote release", message)
        self.assertIn("remote checkout", message)

    def test_deploy_proceeds_without_clashes(self) -> None:
        upload_release, version = self._run_deploy(
            force=False, local_tarball=False, remote_tarball=False, remote_dir=False)
        self.assertEqual(version, "9.9.9")
        _, kwargs = upload_release.call_args
        self.assertTrue(kwargs["overwrite"])

    def test_deploy_overwrites_with_force(self) -> None:
        upload_release, version = self._run_deploy(
            force=True, local_tarball=True, remote_tarball=True, remote_dir=True)
        self.assertEqual(version, "9.9.9")
        _, kwargs = upload_release.call_args
        self.assertTrue(kwargs["overwrite"])


if __name__ == "__main__":
    unittest.main()
