"""Spawn, stop, and restart child world servers with captured output."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import json
import os
import re
import socket
import subprocess
import sys
import threading
import uuid

from server.config import selects_mission_control
from server.mission_control.audit import McAuditLog
from server.mission_control.config import MCConfig
from server.mission_control.registry import (
    SPAWNED,
    STATUS_RUNNING,
    STATUS_STARTING,
    STATUS_STOPPED,
    InstanceRecord,
    InstanceRegistry,
)


RESUME_FILE = "resume.json"


def allocate_port(host: str = "127.0.0.1") -> int:
    """Allocate a free TCP port on *host*."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def route_slug(name: str, taken: set[str]) -> str:
    """Return a unique URL path segment for an instance name."""

    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "world"
    candidate = base
    index = 2
    while candidate in taken:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def sanitize_child_features(raw: str) -> str:
    """Drop mission-control aliases so a spawned child stays a world server."""

    return ",".join(
        part.strip()
        for part in raw.split(",")
        if part.strip() and not selects_mission_control(part)
    )


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
        base_path: str | None = None,
        instance_id: str | None = None,
        instance_dir: str | None = None,
        version_path: Path | None = None,
    ) -> InstanceRecord:
        """Spawn a child ``run.py`` and register it with the instance registry."""

        allocated_port = port or allocate_port(host)
        resolved_dir = Path(instance_dir) if instance_dir else self._config.instances_path / f"mc-{uuid.uuid4().hex[:12]}"
        resolved_dir.mkdir(parents=True, exist_ok=True)
        resolved_worldstate = Path(worldstate_path) if worldstate_path else resolved_dir / "worldstate.sqlite3"
        resolved_users = Path(users_path) if users_path else self._config.users_path
        resolved_base_path = base_path or f"/{route_slug(name, self._taken_routes())}"
        config: dict[str, object] = {
            "name": name,
            "world_path": str(world_path),
            "worldstate_path": str(resolved_worldstate),
            "users_path": str(resolved_users),
            "host": host,
            "port": allocated_port,
            "features": features,
            "admins": admins,
            "mods": mods if mods is not None else self._config.mods,
            "base_path": resolved_base_path,
            "version_path": str(version_path) if version_path is not None else "",
        }
        process = self._spawn_process(config)
        endpoint = f"https://{host}:{allocated_port}"
        record = self._registry.register_spawned(
            instance_id=instance_id,
            name=name,
            endpoint=endpoint,
            instance_dir=str(resolved_dir),
            process_handle=process,
            base_path=resolved_base_path,
            spawn_config=config,
        )
        self._capture_output(record, process)
        self._watch_process(record, process)
        self._audit.record(actor, "instance.start", target=record.instance_id, detail={"endpoint": endpoint})
        return record

    def _taken_routes(self, *, exclude: str | None = None) -> set[str]:
        taken = {
            record.base_path.lstrip("/")
            for record in self._registry.list()
            if record.base_path and record.instance_id != exclude
        }
        taken.add(self._config.admin_route)
        return taken

    def _spawn_process(self, config: dict[str, object]) -> subprocess.Popen:
        env = self._build_env(
            name=str(config["name"]),
            world_path=Path(str(config["world_path"])),
            worldstate_path=Path(str(config["worldstate_path"])),
            users_path=Path(str(config["users_path"])),
            host=str(config["host"]),
            port=int(config["port"]),
            features=str(config.get("features") or ""),
            admins=str(config.get("admins") or ""),
            mods=config.get("mods") if isinstance(config.get("mods"), str) else None,
            base_path=str(config.get("base_path") or ""),
        )
        version_root = Path(str(config.get("version_path") or self._config.repo_root))
        command = [
            sys.executable,
            str(version_root / "run.py"),
            "--host",
            str(config["host"]),
            "--port",
            str(int(config["port"])),
        ]
        return self._spawn(
            command,
            cwd=str(version_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

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
        base_path: str,
    ) -> dict[str, str]:
        env = dict(os.environ)
        for key in [existing for existing in env if existing.startswith("TRSERVER_MC_")]:
            env.pop(key, None)
        env["TRSERVER_WORLD_PATH"] = str(world_path)
        env["TRSERVER_WORLDSTATE_PATH"] = str(worldstate_path)
        env["TRSERVER_USERS_PATH"] = str(users_path)
        env["TRSERVER_HOST"] = host
        env["TRSERVER_PORT"] = str(port)
        env["TRSERVER_BASE_PATH"] = base_path
        env["TRSERVER_NEW_ACCOUNT_PASSPHRASE"] = self._config.new_account_passphrase
        env["TRSERVER_FEATURES"] = sanitize_child_features(features)
        env["TRSERVER_ADMINS"] = admins
        env["TRSERVER_MODS"] = mods if mods is not None else self._config.mods
        env["TRSERVER_MC_ENDPOINT"] = f"{self._config.host}:{self._config.port}"
        env["TRSERVER_MC_TOKEN"] = self._config.token
        env["TRSERVER_MC_NAME"] = name
        env["TRSERVER_SHARED_CONTENT_PATH"] = str(self._config.content_root)
        if self._config.public_origins:
            env["TRSERVER_PUBLIC_ORIGIN"] = ",".join(self._config.public_origins)
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
                if record.process_handle is process:
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
        """Stop and respawn a child in place, keeping its id and public route."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        self.stop(instance_id, actor=actor)
        process = self._spawn_process(dict(record.spawn_config))
        revived = self._registry.revive(instance_id, process_handle=process, instance_dir=record.instance_dir)
        if revived is None:
            return None
        self._capture_output(revived, process)
        self._watch_process(revived, process)
        self._audit.record(actor, "instance.restart", target=instance_id)
        return revived

    def rename(self, instance_id: str, name: str, *, actor: str = "mission-control") -> InstanceRecord | None:
        """Rename a spawned child, changing its public route and restarting it."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        base_path = f"/{route_slug(name, self._taken_routes(exclude=instance_id))}"
        updated = self._registry.rename(instance_id, name, base_path)
        if updated is None:
            return None
        if updated.status != STATUS_STOPPED:
            self.restart(instance_id, actor=actor)
        self._audit.record(actor, "instance.rename", target=instance_id, detail={"name": name, "base_path": base_path})
        return self._registry.get(instance_id)

    def delete(self, instance_id: str, *, actor: str = "mission-control") -> bool:
        """Stop a spawned child and drop it from the registry."""

        record = self._registry.get(instance_id)
        if record is None:
            return False
        self.stop(instance_id, actor=actor)
        self._registry.remove(instance_id)
        self._drop_resume_entry(instance_id)
        self._audit.record(actor, "instance.delete", target=instance_id)
        return True

    def _resume_path(self) -> Path:
        return self._config.instances_path / RESUME_FILE

    def _read_resume(self) -> list[dict[str, object]]:
        path = self._resume_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        entries = data.get("instances") if isinstance(data, dict) else None
        return entries if isinstance(entries, list) else []

    def _write_resume(self, entries: list[dict[str, object]]) -> None:
        path = self._resume_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"instances": entries}, indent=2) + "\n", encoding="utf-8")

    def _clear_resume(self) -> None:
        try:
            self._resume_path().unlink()
        except OSError:
            pass

    def _drop_resume_entry(self, instance_id: str) -> None:
        entries = [entry for entry in self._read_resume() if entry.get("instance_id") != instance_id]
        if entries:
            self._write_resume(entries)
        else:
            self._clear_resume()

    def prepare_reboot(self) -> list[str]:
        """Record running children for resume, then stop them all."""

        entries: list[dict[str, object]] = []
        names: list[str] = []
        for record in self._registry.list():
            if record.source != SPAWNED or record.spawn_config is None:
                continue
            if record.status not in {STATUS_RUNNING, STATUS_STARTING}:
                continue
            entry = dict(record.spawn_config)
            entry["instance_id"] = record.instance_id
            entry["instance_dir"] = record.instance_dir
            entries.append(entry)
            names.append(record.name)
        if entries:
            self._write_resume(entries)
        else:
            self._clear_resume()
        for record in self._registry.list():
            if record.source == SPAWNED:
                self.stop(record.instance_id)
        return names

    def resume_pending(self) -> list[str]:
        """Respawn children recorded by :meth:`prepare_reboot`."""

        entries = self._read_resume()
        if not entries:
            self._clear_resume()
            return []
        started: list[str] = []
        for entry in entries:
            try:
                record = self.start(
                    instance_id=str(entry["instance_id"]) if entry.get("instance_id") else None,
                    name=str(entry.get("name") or "instance"),
                    world_path=Path(str(entry["world_path"])),
                    worldstate_path=Path(str(entry["worldstate_path"])) if entry.get("worldstate_path") else None,
                    users_path=Path(str(entry["users_path"])) if entry.get("users_path") else None,
                    host=str(entry.get("host") or "127.0.0.1"),
                    port=int(entry["port"]) if entry.get("port") else None,
                    features=str(entry.get("features") or ""),
                    admins=str(entry.get("admins") or ""),
                    mods=entry.get("mods") if isinstance(entry.get("mods"), str) else None,
                    base_path=str(entry.get("base_path") or "") or None,
                    instance_dir=str(entry["instance_dir"]) if entry.get("instance_dir") else None,
                    version_path=Path(str(entry["version_path"])) if entry.get("version_path") else None,
                )
                started.append(record.instance_id)
            except (KeyError, OSError, ValueError):
                continue
        self._clear_resume()
        return started
