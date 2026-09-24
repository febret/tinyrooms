"""Spawn, stop, and restart child world servers with captured output."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import os
import socket
import subprocess
import sys
import threading
import uuid

from server.mission_control.audit import McAuditLog
from server.mission_control.config import MCConfig
from server.mission_control.registry import STATUS_STOPPED, InstanceRecord, InstanceRegistry


def allocate_port(host: str = "127.0.0.1") -> int:
    """Allocate a free TCP port on *host*."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class Supervisor:
    """Owns spawned child world-server processes."""

    def __init__(
        self,
        config: MCConfig,
        registry: InstanceRegistry,
        audit: McAuditLog,
        *,
        spawn: Callable[..., subprocess.Popen] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._audit = audit
        self._spawn = spawn or subprocess.Popen

    def start(
        self,
        *,
        name: str,
        world_path: Path,
        worldstate_path: Path | None = None,
        users_path: Path | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        features: str = "",
        admins: str = "",
        mods: str | None = None,
        actor: str = "mission-control",
    ) -> InstanceRecord:
        """Spawn a child ``run.py`` and register it with the instance registry."""

        allocated_port = port or allocate_port(host)
        instance_dir = self._config.instances_path / f"mc-{uuid.uuid4().hex[:12]}"
        instance_dir.mkdir(parents=True, exist_ok=True)
        resolved_worldstate = worldstate_path or (instance_dir / "worldstate.sqlite3")
        env = self._build_env(
            name=name,
            world_path=world_path,
            worldstate_path=resolved_worldstate,
            users_path=users_path or self._config.users_path,
            host=host,
            port=allocated_port,
            features=features,
            admins=admins,
            mods=mods,
        )
        command = [sys.executable, str(self._config.repo_root / "run.py"), "--host", host, "--port", str(allocated_port)]
        process = self._spawn(
            command,
            cwd=str(self._config.repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        endpoint = f"https://{host}:{allocated_port}"
        record = self._registry.register_spawned(
            name=name,
            endpoint=endpoint,
            instance_dir=str(instance_dir),
            process_handle=process,
            spawn_config={
                "name": name,
                "world_path": str(world_path),
                "worldstate_path": str(resolved_worldstate),
                "users_path": str(users_path or self._config.users_path),
                "host": host,
                "port": allocated_port,
                "features": features,
                "admins": admins,
                "mods": mods or self._config.mods,
            },
        )
        self._capture_output(record, process)
        self._watch_process(record, process)
        self._audit.record(actor, "instance.start", target=record.instance_id, detail={"endpoint": endpoint})
        return record

    def _build_env(
        self,
        *,
        name: str,
        world_path: Path,
        worldstate_path: Path,
        users_path: Path,
        host: str,
        port: int,
        features: str,
        admins: str,
        mods: str | None,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env["TRSERVER_WORLD_PATH"] = str(world_path)
        env["TRSERVER_WORLDSTATE_PATH"] = str(worldstate_path)
        env["TRSERVER_USERS_PATH"] = str(users_path)
        env["TRSERVER_HOST"] = host
        env["TRSERVER_PORT"] = str(port)
        env["TRSERVER_NEW_ACCOUNT_PASSPHRASE"] = self._config.new_account_passphrase
        env["TRSERVER_MC_ENDPOINT"] = f"{self._config.host}:{self._config.port}"
        env["TRSERVER_MC_TOKEN"] = self._config.token
        env["TRSERVER_MC_NAME"] = name
        env["TRSERVER_MODS"] = mods if mods is not None else self._config.mods
        if features:
            env["TRSERVER_FEATURES"] = features
        if admins:
            env["TRSERVER_ADMINS"] = admins
        if self._config.ca_file is not None:
            env["TRSERVER_MC_CA_FILE"] = str(self._config.ca_file)
        if self._config.ca_file is None or self._config.insecure_tls:
            env["TRSERVER_MC_INSECURE_TLS"] = "1"
        return env

    def _capture_output(self, record: InstanceRecord, process: subprocess.Popen) -> None:
        stream = getattr(process, "stdout", None)
        if stream is None:
            return

        def _pump() -> None:
            try:
                for line in stream:
                    self._registry.append_log(record.instance_id, line)
            except (OSError, ValueError):
                return

        threading.Thread(target=_pump, name=f"mc-log-{record.instance_id}", daemon=True).start()

    def _watch_process(self, record: InstanceRecord, process: subprocess.Popen) -> None:
        def _wait() -> None:
            try:
                process.wait()
            finally:
                self._registry.set_status(record.instance_id, STATUS_STOPPED)

        threading.Thread(target=_wait, name=f"mc-watch-{record.instance_id}", daemon=True).start()

    def stop(self, instance_id: str, *, actor: str = "mission-control") -> bool:
        """Stop a spawned child process."""

        record = self._registry.get(instance_id)
        if record is None:
            return False
        process = getattr(record, "process_handle", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self._registry.set_status(instance_id, STATUS_STOPPED)
        self._audit.record(actor, "instance.stop", target=instance_id)
        return True

    def restart(self, instance_id: str, *, actor: str = "mission-control") -> InstanceRecord | None:
        """Stop and respawn a child using its original configuration."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        config = dict(record.spawn_config)
        self.stop(instance_id, actor=actor)
        self._registry.remove(instance_id)
        return self.start(actor=actor, **config)  # type: ignore[arg-type]
