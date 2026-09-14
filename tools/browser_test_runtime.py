"""Owned, disposable HTTPS server for browser tests; never opens live state."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.parent != ROOT / ".browser-runtime" or not directory.is_dir():
        parser.error("Runtime directory must be an existing child of .browser-runtime.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config = load_config(env={
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "browser-test-invitation",
            "TRSERVER_USERS_PATH": str(directory / "users"),
            "TRSERVER_WORLDSTATE_PATH": str(directory / "worldstate.sqlite3"),
            "TRSERVER_WORLD_PATH": str(ROOT / "worlds" / "tutorial"),
            "TRSERVER_FEATURES": "dev_sample_activity",
            "TRSERVER_TIMEZONE": "UTC",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": str(port),
        }, repo_root=ROOT)
        config = replace(config, local_path=directory)
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
