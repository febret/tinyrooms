"""Owned, disposable HTTPS server for browser tests; never opens live state."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import threading
import time

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run import ensure_self_signed_certificate
from server.app import create_app
from server.config import load_config


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _prepare_world(directory: Path) -> Path:
    """Copy the tutorial world into the run directory so publishes stay isolated.

    The directory keeps the world id as its name because world-card scope is
    derived from the directory name during catalog loading.

    ``--world-scale`` swaps the plain copy for a generated one, which is how the
    performance suite gets a room crowded enough to measure. It is opt-in so the
    functional suite keeps running against the authored content.
    """

    scale_arg = os.environ.get("TR_PERF_WORLD_SCALE", "").strip()
    if scale_arg:
        from tools.perf_world import build_scaled_world, parse_scale

        return build_scaled_world(directory, **parse_scale(scale_arg))
    world_path = directory / "tutorial"
    if not world_path.is_dir():
        shutil.copytree(ROOT / "worlds" / "tutorial", world_path, copy_function=_link_or_copy)
    return world_path


def _prepare_fx(directory: Path) -> Path:
    """Copy the shared effect definitions so Prop Editor writes stay isolated."""

    fx_path = directory / "fx"
    if not fx_path.is_dir():
        shutil.copytree(ROOT / "data" / "fx", fx_path, copy_function=_link_or_copy)
    return fx_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.parent != ROOT / ".browser-runtime" or not directory.is_dir():
        parser.error("Runtime directory must be an existing child of .browser-runtime.")
    world_path = _prepare_world(directory)
    fx_path = _prepare_fx(directory)
    drafts_path = directory / "drafts"
    drafts_path.mkdir(parents=True, exist_ok=True)
    revisions_path = directory / "revisions"
    revisions_path.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config = load_config(env={
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "browser-test-invitation",
            "TRSERVER_USERS_PATH": str(directory / "users"),
            "TRSERVER_WORLDSTATE_PATH": str(directory / "worldstate.sqlite3"),
            "TRSERVER_WORLD_PATH": str(world_path),
            "TRSERVER_FX_PATH": str(fx_path),
            "TRSERVER_FEATURES": "dev_sample_activity,world-editor,card-database,prop-editor",
            "TRSERVER_MODS": "*",
            "TRSERVER_ADMINS": "siteadmin",
            "TRSERVER_TIMEZONE": "UTC",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": str(port),
        }, repo_root=ROOT)
        config = replace(
            config,
            local_path=directory,
            drafts_path=drafts_path,
            revisions_path=revisions_path,
        )
        cert, key = ensure_self_signed_certificate(directory, "127.0.0.1")
        server = uvicorn.Server(uvicorn.Config(
            create_app(config), host="127.0.0.1", port=port,
            ssl_certfile=str(cert), ssl_keyfile=str(key), log_level="warning",
        ))

        def watch_owner() -> None:
            sys.stdin.buffer.read()
            server.should_exit = True

        def announce() -> None:
            while not server.started and not server.should_exit:
                time.sleep(0.02)
            if server.started:
                print(json.dumps({"baseURL": f"https://127.0.0.1:{port}"}), flush=True)

        threading.Thread(target=watch_owner, daemon=True).start()
        threading.Thread(target=announce, daemon=True).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
