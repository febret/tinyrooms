"""Tests for the fleet_restart helper used by deploy --force-restart."""

from __future__ import annotations

import http.client
import http.server
import importlib.util
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fleet_restart", REPO_ROOT / "tools" / "fleet_restart.py")
fleet = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = fleet
SPEC.loader.exec_module(fleet)


def make_server(instance_id: str, status: str, source: str = "spawned",
               name: str = "", world: str = "tinytown", version: str | None = "0.4.1") -> fleet.Server:
    """Build one instance record for target-selection tests."""

    return fleet.Server(instance_id=instance_id, name=name or instance_id, world=world,
                        status=status, source=source, version=version)


class SelectTargetsTests(unittest.TestCase):
    def test_running_and_starting_spawned_instances_are_targets(self) -> None:
        servers = [
            make_server("a", "running"),
            make_server("b", "starting"),
            make_server("c", "stopped"),
        ]
        targets, skipped = fleet.select_targets(servers)
        self.assertEqual([server.instance_id for server in targets], ["a", "b"])
        self.assertEqual(skipped, [])

    def test_external_running_instances_are_skipped_with_reason(self) -> None:
        servers = [make_server("x", "running", source="external", name="Legacy")]
        targets, skipped = fleet.select_targets(servers)
        self.assertEqual(targets, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["instance_id"], "x")
        self.assertIn("external", skipped[0]["reason"])

    def test_unreachable_spawned_instances_are_skipped(self) -> None:
        servers = [make_server("u", "unreachable", name="Ghost")]
        targets, skipped = fleet.select_targets(servers)
        self.assertEqual(targets, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("unreachable", skipped[0]["reason"])


class FakeClient:
    """Scripted stand-in for McClient."""

    def __init__(self, servers: list[fleet.Server], *, fail_change: set[str] | None = None,
                 hang: set[str] | None = None) -> None:
        self.servers = {server.instance_id: server for server in servers}
        self.fail_change = fail_change or set()
        self.hang = hang or set()
        self.changed: list[str] = []

    def list_servers(self) -> list[fleet.Server]:
        return list(self.servers.values())

    def change_version(self, instance_id: str, version: str) -> None:
        if instance_id in self.fail_change:
            raise fleet.McError(f"World 'tinytown' is not installed for version {version}.")
        self.changed.append(instance_id)
        self.servers[instance_id].version = version
        self.servers[instance_id].status = "starting"

    def wait_ready(self, instance_id: str, version: str, timeout: float, poll_interval: float = 0,
                   *, clock=None, sleep=None) -> None:
        if instance_id in self.hang:
            raise fleet.McError(f"Instance {instance_id} did not report version {version} in time.")
        self.servers[instance_id].status = "running"


class RestartFleetTests(unittest.TestCase):
    def test_successful_roll_emits_ordered_events(self) -> None:
        client = FakeClient([make_server("a", "running", name="Tiny Town")])
        events: list[dict[str, object]] = []
        failures = fleet.restart_fleet(client, "0.4.2", events.append,
                                       timeout=5, poll_interval=0, sleep=lambda seconds: None)
        kinds = [(event["type"], event.get("status")) for event in events]
        self.assertEqual(failures, [])
        self.assertEqual(kinds[0], ("begin", None))
        self.assertEqual(kinds[1], ("instance", "updating"))
        self.assertEqual(kinds[2], ("instance", "waiting"))
        self.assertEqual(kinds[3], ("instance", "ready"))
        self.assertEqual(kinds[4], ("done", None))
        self.assertEqual(events[0]["total"], 1)
        self.assertEqual(events[-1]["updated"], 1)

    def test_failed_change_is_recorded_and_roll_continues(self) -> None:
        client = FakeClient(
            [make_server("a", "running", name="Alpha"), make_server("b", "running", name="Beta")],
            fail_change={"a"},
        )
        events: list[dict[str, object]] = []
        failures = fleet.restart_fleet(client, "0.4.2", events.append,
                                       timeout=5, poll_interval=0, sleep=lambda seconds: None)
        self.assertEqual(failures, ["Alpha (tinytown)"])
        self.assertIn("b", client.changed)
        self.assertEqual(events[-1]["failed"], 1)

    def test_timeout_is_reported_as_failure(self) -> None:
        client = FakeClient([make_server("a", "running", name="Alpha")], hang={"a"})
        events: list[dict[str, object]] = []
        failures = fleet.restart_fleet(client, "0.4.2", events.append,
                                       timeout=5, poll_interval=0, sleep=lambda seconds: None)
        self.assertEqual(failures, ["Alpha (tinytown)"])
        failed = [event for event in events if event.get("status") == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("did not report", str(failed[0]["message"]))

    def test_no_targets_still_emits_begin_and_done(self) -> None:
        client = FakeClient([make_server("c", "stopped")])
        events: list[dict[str, object]] = []
        failures = fleet.restart_fleet(client, "0.4.2", events.append, sleep=lambda seconds: None)
        self.assertEqual(failures, [])
        self.assertEqual([event["type"] for event in events], ["begin", "done"])
        self.assertEqual(events[0]["total"], 0)


class ParseArgsTests(unittest.TestCase):
    def test_version_is_required(self) -> None:
        args = fleet.parse_args(["--version", "0.4.2", "--port", "8001"])
        self.assertEqual(args.version, "0.4.2")
        self.assertEqual(args.port, "8001")
        self.assertEqual(args.timeout, 90.0)


class StubMcHandler(http.server.BaseHTTPRequestHandler):
    """Minimal Mission Control stub that enforces JSON bodies like FastAPI.

    POSTs without ``Content-Type: application/json`` are rejected with the
    same 400 payload the real app returns, so a client that forgets the
    header fails here exactly as it does against production.
    """

    def log_message(self, *args: object) -> None:
        pass

    @property
    def state(self) -> dict[str, object]:
        return self.server.state  # type: ignore[attr-defined]

    def _send_json(self, status: int, payload: dict[str, object], cookies: tuple[str, ...] = ()) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _is_json_body(self) -> bool:
        return "application/json" in self.headers.get("Content-Type", "")

    def _read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _invalid_payload(self) -> None:
        self._send_json(400, {"ok": False, "code": "invalid_request", "message": "Invalid request payload."})

    def _authenticated(self) -> bool:
        return "tr_mc_session=sess-1" in self.headers.get("Cookie", "")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        self.state.setdefault("content_types", []).append(self.headers.get("Content-Type", ""))
        if self.path == "/api/mission-control/auth/login":
            if not self._is_json_body():
                self._invalid_payload()
                return
            payload = self._read_json()
            if payload is None or payload.get("passphrase") != self.state["passphrase"]:
                self._send_json(401, {"ok": False, "message": "Incorrect passphrase."})
                return
            self._send_json(200, {"ok": True, "operator": "operator", "csrf_token": "csrf-1"},
                            ("tr_mc_session=sess-1; Path=/", "tr_mc_csrf=csrf-1; Path=/"))
            return
        if self.path.startswith("/api/mission-control/servers/") and self.path.endswith("/version"):
            if not self._is_json_body():
                self._invalid_payload()
                return
            if not self._authenticated():
                self._send_json(401, {"ok": False, "message": "Authentication required."})
                return
            if self.headers.get("Origin") != self.state["origin"]:
                self._send_json(403, {"ok": False, "message": "Origin is not allowed."})
                return
            if self.headers.get("X-CSRF-Token") != "csrf-1":
                self._send_json(403, {"ok": False, "message": "Invalid CSRF token."})
                return
            instance_id = self.path.split("/")[-2]
            servers = self.state["servers"]
            assert isinstance(servers, dict)
            record = servers.get(instance_id)
            if record is None:
                self._send_json(404, {"ok": False, "message": "Instance not found."})
                return
            payload = self._read_json()
            record["version"] = str((payload or {}).get("version") or "")
            record["status"] = "starting"
            self._send_json(200, {"ok": True, "server": dict(record)})
            return
        self._send_json(404, {"ok": False, "message": "Not Found."})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        if self.path != "/api/mission-control/servers":
            self._send_json(404, {"ok": False, "message": "Not Found."})
            return
        if not self._authenticated():
            self._send_json(401, {"ok": False, "message": "Authentication required."})
            return
        servers = self.state["servers"]
        assert isinstance(servers, dict)
        for record in servers.values():
            # Re-registration flips a restarted child back to running.
            if record["status"] == "starting" and record.get("version"):
                record["status"] = "running"
        self._send_json(200, {"ok": True, "servers": [dict(record) for record in servers.values()],
                              "summary": {"total": len(servers)}})


class LiveStubMcTests(unittest.TestCase):
    """Exercise the real HTTP client against a stub Mission Control server."""

    def setUp(self) -> None:
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubMcHandler)
        self.httpd.state = {
            "passphrase": "op-pass",
            "origin": "https://example.com",
            "servers": {
                "a": {"instance_id": "a", "name": "Tiny Town",
                      "world": {"id": "tinytown"}, "status": "running",
                      "source": "spawned", "version": "0.4.1", "endpoint": "https://127.0.0.1:1"},
            },
        }
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        port = self.httpd.server_address[1]
        self.client = fleet.McClient(f"http://127.0.0.1:{port}", "https://example.com")
        self.client.login("op-pass")

    def test_roll_updates_and_restarts_running_instance(self) -> None:
        events: list[dict[str, object]] = []
        failures = fleet.restart_fleet(self.client, "0.4.2", events.append,
                                       timeout=5, poll_interval=0.01)
        self.assertEqual(failures, [])
        kinds = [(event["type"], event.get("status")) for event in events]
        self.assertEqual(kinds, [("begin", None), ("instance", "updating"), ("instance", "waiting"),
                                 ("instance", "ready"), ("done", None)])
        self.assertEqual(events[-1]["updated"], 1)
        posts = [content for content in self.httpd.state["content_types"] if content]
        self.assertTrue(posts)
        for content in posts:
            self.assertIn("application/json", content)

    def test_stub_rejects_json_body_without_json_content_type(self) -> None:
        port = self.httpd.server_address[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/mission-control/auth/login",
            data=json.dumps({"passphrase": "op-pass"}).encode("utf-8"),
            method="POST",
        )
        # Windows loopback tears down stub connections sporadically; retry those.
        response: urllib.error.HTTPError | None = None
        for attempt in range(3):
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
                break
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError,
                    http.client.RemoteDisconnected) as exc:
                if attempt == 2:
                    raise AssertionError(f"stub server unreachable: {exc}") from exc
                time.sleep(0.1)
        assert response is not None
        self.assertEqual(response.code, 400)
        payload = json.load(response)
        response.close()
        self.assertEqual(payload["message"], "Invalid request payload.")


if __name__ == "__main__":
    unittest.main()
