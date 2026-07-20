from __future__ import annotations

import collections
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
import socketio
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_OWNER_USERNAME = "it_owner"
TEST_OWNER_PASSWORD = "it_owner_password"


@dataclass
class ServerRuntime:
    workspace: Path
    process: subprocess.Popen[str]
    base_url: str
    char_temp_dir: Path


class SocketCaptureClient:
    _EVENT_NAMES = (
        "connected",
        "actions_def",
        "login_success",
        "login_failed",
        "message",
        "error",
        "activity_panel",
        "update_view",
        "set_skin",
        "reload_styles",
        "reload_client",
    )

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._client = socketio.Client(reconnection=False, logger=False, engineio_logger=False)
        self._events: dict[str, collections.deque[Any]] = collections.defaultdict(collections.deque)
        self._cond = threading.Condition()

        for event_name in self._EVENT_NAMES:
            self._client.on(event_name, self._make_handler(event_name))

    def _make_handler(self, event_name: str):
        def _handler(payload=None):
            with self._cond:
                self._events[event_name].append(payload if payload is not None else {})
                self._cond.notify_all()

        return _handler

    def connect(self, timeout: float = 8.0):
        self._client.connect(self.base_url, transports=["polling"], wait=True, wait_timeout=timeout)
        return self

    def disconnect(self):
        if self._client.connected:
            self._client.disconnect()

    def emit(self, event_name: str, payload: dict[str, Any] | None = None):
        self._client.emit(event_name, payload or {})

    def wait_for(
        self,
        event_name: str,
        predicate: Callable[[Any], bool] | None = None,
        timeout: float = 6.0,
    ) -> Any:
        deadline = time.monotonic() + timeout
        while True:
            with self._cond:
                queue = self._events[event_name]
                while queue:
                    payload = queue.popleft()
                    if predicate is None or predicate(payload):
                        return payload
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"timed out waiting for socket event '{event_name}'")
                self._cond.wait(timeout=remaining)

    def drain(self, event_name: str) -> list[Any]:
        with self._cond:
            queue = self._events[event_name]
            out = list(queue)
            queue.clear()
            return out


def _write_stub_make_image(workspace: Path):
    script_path = workspace / "tools" / "make-image"
    script = """#!/usr/bin/env python3
import argparse
import base64
import json
import pathlib
import time

PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7g2k0AAAAASUVORK5CYII=")

parser = argparse.ArgumentParser()
parser.add_argument("output_path")
parser.add_argument("--size", default="64x64")
parser.add_argument("--description", default="")
parser.add_argument("--descriptors-json", default="")
parser.add_argument("--style", default="")
parser.add_argument("--border-color", default="")
parser.add_argument("--glow-color", default="")

args = parser.parse_args()
out = pathlib.Path(args.output_path)
out.parent.mkdir(parents=True, exist_ok=True)

descriptors = {}
if args.descriptors_json:
    descriptors = json.loads(args.descriptors_json)
    if not isinstance(descriptors, dict):
        raise SystemExit("descriptors must be an object")
if not str(args.description).strip() and not descriptors:
    raise SystemExit("description or descriptors are required")

time.sleep(0.6)
out.write_bytes(PNG_1X1)
print(f"stub make-image wrote {out} ({args.size})")
"""
    script_path.write_text(script, encoding="utf-8")


def _prepare_isolated_workspace(workspace: Path):
    rooms_path = workspace / "data" / "worlds" / "home" / "rooms" / "rooms.yaml"
    with rooms_path.open("r", encoding="utf-8") as handle:
        rooms = yaml.safe_load(handle) or {}
    playroom = rooms.get("playroom")
    if isinstance(playroom, dict):
        playroom["owner_id"] = TEST_OWNER_USERNAME
    with rooms_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(rooms, handle, sort_keys=False)
    _write_stub_make_image(workspace)


def _wait_for_server(base_url: str, timeout_seconds: float = 20.0):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=1.0) as client:
                response = client.get(f"{base_url}/connected")
            if response.status_code == 200:
                return
        except Exception as err:  # network errors while server boots
            last_error = err
        time.sleep(0.2)
    if last_error:
        raise RuntimeError(f"server did not become ready: {last_error}")
    raise RuntimeError("server did not become ready")


def _poll_until(
    fn: Callable[[], Any],
    predicate: Callable[[Any], bool],
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.2,
):
    deadline = time.monotonic() + timeout_seconds
    latest = None
    while time.monotonic() < deadline:
        latest = fn()
        if predicate(latest):
            return latest
        time.sleep(interval_seconds)
    return latest


@pytest.fixture(scope="session")
def integration_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    parent = tmp_path_factory.mktemp("tinyrooms-it")
    workspace = parent / "workspace"
    ignore = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".pytest_cache",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "*.duckdb",
    )
    shutil.copytree(REPO_ROOT, workspace, ignore=ignore)
    _prepare_isolated_workspace(workspace)
    return workspace


@pytest.fixture(scope="session")
def server_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server_runtime(integration_workspace: Path, server_port: int) -> ServerRuntime:
    char_temp_dir = integration_workspace / "char-temp"
    command = [
        sys.executable,
        "trserver.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(server_port),
        "--char-temp-dir",
        str(char_temp_dir),
        "--feature",
        "sprite-editor",
    ]
    proc = subprocess.Popen(
        command,
        cwd=integration_workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    runtime = ServerRuntime(
        workspace=integration_workspace,
        process=proc,
        base_url=f"http://127.0.0.1:{server_port}",
        char_temp_dir=char_temp_dir,
    )
    try:
        _wait_for_server(runtime.base_url)
        yield runtime
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=6)


@pytest.fixture
def http_client(server_runtime: ServerRuntime):
    with httpx.Client(base_url=server_runtime.base_url, timeout=6.0) as client:
        yield client


@pytest.fixture
def unique_username() -> Callable[[str], str]:
    def _make(prefix: str = "it_user") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    return _make


@pytest.fixture
def register_user(http_client: httpx.Client):
    def _register(username: str, password: str):
        response = http_client.post("/register", json={"username": username, "password": password})
        assert response.status_code == 201, response.text
        return response.json()

    return _register


@pytest.fixture
def socket_client_factory(server_runtime: ServerRuntime):
    clients: list[SocketCaptureClient] = []

    def _create() -> SocketCaptureClient:
        client = SocketCaptureClient(server_runtime.base_url).connect()
        clients.append(client)
        return client

    yield _create
    for client in clients:
        client.disconnect()


@pytest.fixture
def login_socket_user():
    def _login(client: SocketCaptureClient, username: str, password: str) -> dict[str, Any]:
        client.emit("login", {"username": username, "password": password})
        success = _poll_until(
            lambda: client.drain("login_success"),
            lambda events: any(e.get("username") == username for e in events),
            timeout_seconds=6.0,
            interval_seconds=0.1,
        )
        if success:
            for payload in success:
                if payload.get("username") == username:
                    return payload
        failed = client.drain("login_failed")
        raise AssertionError(f"login failed for {username}: {failed}")

    return _login


@pytest.fixture
def owner_account(http_client: httpx.Client):
    response = http_client.post(
        "/register",
        json={"username": TEST_OWNER_USERNAME, "password": TEST_OWNER_PASSWORD},
    )
    assert response.status_code in {201, 409}, response.text
    return {"username": TEST_OWNER_USERNAME, "password": TEST_OWNER_PASSWORD}


@pytest.fixture
def poll_until_terminal(http_client: httpx.Client):
    def _poll(request_id: str, headers: dict[str, str], timeout_seconds: float = 12.0):
        response = _poll_until(
            lambda: http_client.get(f"/api/char-editor/requests/{request_id}", headers=headers),
            lambda res: res.status_code == 200 and res.json()["request"]["status"] in {"done", "failed", "cancelled"},
            timeout_seconds=timeout_seconds,
            interval_seconds=0.2,
        )
        assert isinstance(response, httpx.Response)
        assert response.status_code == 200, response.text
        return response.json()["request"]

    return _poll


@pytest.fixture
def auth_socket_user(socket_client_factory, login_socket_user, register_user, unique_username):
    def _create(prefix: str = "it_auth_user", password: str = "password123"):
        username = unique_username(prefix)
        register_user(username, password)
        client = socket_client_factory()
        login_payload = login_socket_user(client, username, password)
        return {
            "username": username,
            "password": password,
            "client": client,
            "login": login_payload,
            "headers": {"X-TR-Auth": login_payload["rest_token"]},
        }

    return _create
