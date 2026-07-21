from __future__ import annotations

import base64
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
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7g2k0AAAAASUVORK5CYII=")


@dataclass
class ServerRuntime:
    workspace: Path
    process: subprocess.Popen[str]
    base_url: str
    char_temp_dir: Path


class SocketCaptureClient:
    _EVENT_NAMES = (
        "connected",
        "emotes_def",
        "login_success",
        "login_failed",
        "message",
        "error",
        "activity_panel",
        "update_view",
        "inventory_update",
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


def _reset_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_1X1)


def _write_yaml(path: Path, payload: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_test_sprite_set(root: Path, stem: str, label: str, sprite_id: str):
    _write_png(root / f"{stem}.png")
    _write_yaml(
        root / f"{stem}.yaml",
        {
            "label": label,
            "description": f"{label} description",
            "frame_width": 32,
            "frame_height": 32,
            "sprites": {
                sprite_id: {
                    "default_frame": "0x0",
                    "anims": {
                        "idle": {
                            "speed": 0.5,
                            "type": "loop",
                            "frames": ["0x0"],
                        }
                    },
                }
            },
        },
    )


def _write_test_peep_definitions(workspace: Path):
    """Write test NPC peep class YAML and behavior script."""
    peeps_dir = workspace / "data" / "peeps"
    peeps_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(
        peeps_dir / "test_peeps.yaml",
        {
            "test_greeter": {
                "label": "Greeter",
                "description": "A friendly greeter NPC used in integration tests.",
                "img": "images/test_object.png",
                "behavior": "test_greeter",
            }
        },
    )
    # Write the behavior script alongside the YAML
    behavior_script = """\
tick_count = 0

def on_tick(secs):
    global tick_count
    tick_count += 1

def on_message(src, text):
    src_label = getattr(src, 'username', getattr(src, 'peep_id', str(src)))
    text_lower = str(text).lower()
    if 'hello' in text_lower:
        say(f'Hello, {src_label}!')
    elif 'tick_count' in text_lower:
        say(f'Ticks: {tick_count}')
    elif 'move_test' in text_lower:
        move(100, 100)
    elif 'error_test' in text_lower:
        raise RuntimeError('intentional behavior error')
    else:
        say(f'You said: {text}')
"""
    (peeps_dir / "test_greeter.py").write_text(behavior_script, encoding="utf-8")


def _write_test_world_definitions(workspace: Path):
    world_root = workspace / "data" / "worlds" / "home"
    _reset_dir(workspace / "data" / "props")
    _reset_dir(workspace / "data" / "sprites")
    _reset_dir(world_root / "sprites")
    _reset_dir(world_root / "props")
    _reset_dir(world_root / "rooms")
    _reset_dir(world_root / "things")

    _write_yaml(world_root / "world.yaml", {"label": "Integration Test World"})
    _write_yaml(
        world_root / "rooms" / "rooms.yaml",
        {
            "DEFAULT_ROOM": {
                "type": "room",
                "label": "the Test Void",
                "description": "A simple default room used by integration tests.",
                "image": "images/test_void.png",
                "stage": {
                    "type": "basic",
                    "width": 400,
                    "height": 300,
                    "background_mode": "stretch",
                },
                "ways": "to_gateway",
                "peeps": [
                    {"peep_id": "greeter_npc", "class": "test_greeter", "x": 200, "y": 150},
                ],
            },
            "to_gateway": {
                "type": "way",
                "label": "through the integration gateway",
                "to": "playroom",
            },
            "playroom": {
                "type": "room",
                "owner_id": TEST_OWNER_USERNAME,
                "label": "the Playroom",
                "description": "A test playroom with a single movable object and editable props.",
                "image": "images/test_playroom.png",
                "stage": {
                    "type": "basic",
                    "width": 256,
                    "height": 512,
                    "background_mode": "stretch",
                    "theme": "home",
                },
                "init_things": ["test_statue"],
                "props": ["floor_rug", "standing_lamp"],
            },
        },
    )
    _write_yaml(
        world_root / "things" / "things.yaml",
        {
            "test_statue": {
                "type": "object",
                "label": "a test statue",
                "description": "A small object created by the integration harness.",
                "img": "images/test_object.png",
                "sprite": "images/test_object.png",
                "icon": "img:images/test_object.png",
                "tags": ["item"],
            }
        },
    )
    _write_yaml(
        workspace / "data" / "props" / "test_room_props.yaml",
        {
            "label": "Integration Props",
            "description": "Props created by the test harness.",
            "image": "test_room_props.png",
            "props": {
                "floor_rug": {
                    "width": 64,
                    "height": 32,
                    "frames": [[0, 0]],
                },
                "standing_lamp": {
                    "width": 32,
                    "height": 64,
                    "frames": [[64, 0]],
                },
                "wall_clock": {
                    "width": 32,
                    "height": 32,
                    "frames": [[96, 0]],
                },
            },
        },
    )
    _write_png(workspace / "data" / "props" / "test_room_props.png")
    _write_test_sprite_set(workspace / "data" / "sprites", "server_people", "Server People", "server_knight")
    _write_test_sprite_set(world_root / "sprites", "world_people", "World People", "world_ranger")
    _write_png(world_root / "images" / "test_void.png")
    _write_png(world_root / "images" / "test_playroom.png")
    _write_png(world_root / "images" / "test_object.png")


def _prepare_isolated_workspace(workspace: Path):
    _write_test_world_definitions(workspace)
    _write_test_peep_definitions(workspace)
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
        "*.duckdb.wal",
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
        "sprite-editor,world-server",
        "--tick-secs",
        "0.5",
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
