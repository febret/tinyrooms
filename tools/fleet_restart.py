"""Roll every running Mission Control instance onto one installed version.

This helper is invoked remotely by ``tools/deploy.py --force-restart``
after a release has been installed and activated. It logs in to the local
Mission Control listener with the operator passphrase from the shell
environment, switches each running spawned instance to the deployed
version (which restarts it), then waits for every child to report the
expected build before exiting.

Progress is emitted as one JSON object per line so the deploy script can
render live status. Exit codes: 0 when every target restarted, 1 when one
or more instances failed, 2 when Mission Control could not be reached,
3 for login/configuration errors.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass


RUNNING_STATUSES = ("running", "starting")

EXIT_OK = 0
EXIT_INSTANCE_FAILURES = 1
EXIT_UNREACHABLE = 2
EXIT_AUTH_ERROR = 3


class McError(RuntimeError):
    """Raised when a Mission Control request fails."""

    def __init__(self, message: str, *, kind: str = "api", status: int = 0) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class Server:
    """One instance record returned by the Mission Control server list."""

    instance_id: str
    name: str
    world: str
    status: str
    source: str
    version: str | None


def server_label(server: Server) -> str:
    """Return a human-readable label for an instance."""

    if server.name and server.world:
        return f"{server.name} ({server.world})"
    return server.name or server.instance_id


def select_targets(servers: list[Server]) -> tuple[list[Server], list[dict[str, str]]]:
    """Split servers into restart targets and skipped entries with reasons."""

    targets: list[Server] = []
    skipped: list[dict[str, str]] = []
    for server in servers:
        if server.status in RUNNING_STATUSES:
            if server.source == "spawned":
                targets.append(server)
            else:
                skipped.append({
                    "instance_id": server.instance_id,
                    "name": server.name,
                    "reason": "external instance; its version is not managed by this deployment",
                })
        elif server.status == "unreachable" and server.source == "spawned":
            skipped.append({
                "instance_id": server.instance_id,
                "name": server.name,
                "reason": "status unreachable; leaving it unchanged",
            })
    return targets, skipped


class McClient:
    """Minimal operator client for the Mission Control management API."""

    def __init__(self, base_url: str, origin: str, *, timeout: float = 10.0) -> None:
        context = ssl._create_unverified_context()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self._base_url = base_url.rstrip("/")
        self._origin = origin
        self._timeout = timeout
        self._csrf: str | None = None

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        """Send one JSON request and return its status and decoded payload."""

        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self._base_url + path, data=data, method=method)
        # urllib defaults POST bodies to application/x-www-form-urlencoded, which
        # FastAPI will not parse as JSON; declare the JSON body explicitly.
        if data is not None:
            request.add_header("Content-Type", "application/json")
        request.add_header("Origin", self._origin)
        if self._csrf is not None:
            request.add_header("X-CSRF-Token", self._csrf)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
            except ValueError:
                payload = {"ok": False, "message": f"HTTP {exc.code}"}
            if exc.code in (401, 403):
                raise McError(str(payload.get("message") or "Operator login failed."), kind="auth", status=exc.code) from exc
            message = str(payload.get("message") or payload.get("detail") or f"HTTP {exc.code}")
            raise McError(message, kind="api", status=exc.code) from exc
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            raise McError(str(exc) or type(exc).__name__, kind="connection") from exc
        if not isinstance(payload, dict):
            raise McError("Unexpected Mission Control response.", kind="api")
        return 0, payload

    def login(self, passphrase: str) -> None:
        """Authenticate as the operator and capture the session CSRF token."""

        _, payload = self._request("POST", "/api/mission-control/auth/login", {"passphrase": passphrase})
        csrf = payload.get("csrf_token")
        if payload.get("ok") is not True or not csrf:
            raise McError("Operator login failed.", kind="auth", status=401)
        self._csrf = str(csrf)

    @staticmethod
    def _server(payload: dict[str, object]) -> Server:
        world = payload.get("world")
        return Server(
            instance_id=str(payload.get("instance_id") or ""),
            name=str(payload.get("name") or ""),
            world=str(world.get("id")) if isinstance(world, dict) and world.get("id") else "",
            status=str(payload.get("status") or ""),
            source=str(payload.get("source") or ""),
            version=payload.get("version") if isinstance(payload.get("version"), str) else None,
        )

    def list_servers(self) -> list[Server]:
        """Return every instance known to Mission Control."""

        _, payload = self._request("GET", "/api/mission-control/servers")
        if payload.get("ok") is not True:
            raise McError(str(payload.get("message") or "Could not list servers."))
        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise McError("Unexpected server list response.")
        return [self._server(item) for item in servers if isinstance(item, dict)]

    def change_version(self, instance_id: str, version: str) -> None:
        """Point one spawned instance at another installed version and restart it."""

        _, payload = self._request(
            "POST",
            f"/api/mission-control/servers/{urllib.parse.quote(instance_id, safe='')}/version",
            {"version": version},
        )
        if payload.get("ok") is not True:
            raise McError(str(payload.get("message") or f"Version change failed for {instance_id}."))

    def wait_ready(
        self,
        instance_id: str,
        version: str,
        timeout: float,
        poll_interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Wait until one instance runs the expected version."""

        deadline = clock() + timeout
        while True:
            for server in self.list_servers():
                if server.instance_id == instance_id and server.status == "running" and server.version == version:
                    return
            if clock() >= deadline:
                raise McError(f"Instance {instance_id} did not report version {version} in time.")
            sleep(poll_interval)


def restart_fleet(
    client: McClient,
    version: str,
    emit: Callable[[dict[str, object]], None],
    *,
    timeout: float = 90.0,
    poll_interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Restart every running spawned instance on *version*; return failed labels."""

    servers = client.list_servers()
    targets, skipped = select_targets(servers)
    emit({"type": "begin", "version": version, "total": len(targets), "skipped": skipped})
    failures: list[str] = []
    updated = 0
    for server in targets:
        label = server_label(server)
        detail = {
            "instance_id": server.instance_id,
            "name": server.name,
            "world": server.world,
            "version": version,
        }
        emit({**detail, "type": "instance", "status": "updating", "from_version": server.version})
        started = clock()
        try:
            client.change_version(server.instance_id, version)
        except McError as exc:
            failures.append(label)
            emit({**detail, "type": "instance", "status": "failed", "message": str(exc)})
            continue
        emit({**detail, "type": "instance", "status": "waiting"})
        try:
            client.wait_ready(server.instance_id, version, timeout, poll_interval, clock=clock, sleep=sleep)
        except McError as exc:
            failures.append(label)
            emit({**detail, "type": "instance", "status": "failed", "message": str(exc)})
            continue
        updated += 1
        emit({**detail, "type": "instance", "status": "ready", "elapsed": round(clock() - started, 1)})
    emit({"type": "done", "updated": updated, "skipped": len(skipped), "failed": len(failures), "failures": failures})
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Restart every running Mission Control instance on one version.")
    parser.add_argument("--base-url", help="Mission Control base URL (default: https://127.0.0.1:<port>).")
    parser.add_argument("--port", help="Loopback Mission Control port (uses TRSERVER_MC_PORT when omitted).")
    parser.add_argument("--version", required=True, help="Installed version label to restart instances on.")
    parser.add_argument("--timeout", type=float, default=90.0, help="Seconds to wait per instance (default: 90).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Log in locally and roll every running spawned instance onto one version."""

    args = parse_args(argv)

    def emit(event: dict[str, object]) -> None:
        print(json.dumps(event), flush=True)

    port = args.port or os.environ.get("TRSERVER_MC_PORT", "")
    base_url = args.base_url or (f"https://127.0.0.1:{port}" if port else "")
    passphrase = os.environ.get("TRSERVER_MC_PASSPHRASE", "")
    origin = os.environ.get("TRSERVER_MC_PUBLIC_ORIGIN", "")
    if not base_url or not passphrase or not origin:
        emit({"type": "error", "message": "TRSERVER_MC_PORT/base URL, passphrase, and public origin are required."})
        return EXIT_AUTH_ERROR
    client = McClient(base_url, origin)
    try:
        client.login(passphrase)
    except McError as exc:
        if exc.kind == "connection":
            emit({"type": "error", "code": "unreachable", "message": f"Mission Control is not reachable: {exc}"})
            return EXIT_UNREACHABLE
        emit({"type": "error", "code": "auth", "message": str(exc)})
        return EXIT_AUTH_ERROR
    try:
        failures = restart_fleet(client, args.version, emit, timeout=args.timeout)
    except McError as exc:
        if exc.kind == "connection":
            emit({"type": "error", "code": "unreachable", "message": f"Mission Control is not reachable: {exc}"})
            return EXIT_UNREACHABLE
        emit({"type": "error", "message": str(exc)})
        return EXIT_AUTH_ERROR
    return EXIT_OK if not failures else EXIT_INSTANCE_FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
