"""Spawn, stop, and restart child world servers with captured output."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from server.config import normalize_base_path, selects_mission_control, validate_instance_id
from server.mission_control.audit import McAuditLog
from server.mission_control.config import MCConfig
from server.mission_control.registry import (
    SPAWNED,
    STATUS_RUNNING,
    STATUS_STARTING,
    STATUS_STOPPED,
    STATUS_UNREACHABLE,
    InstanceRecord,
    InstanceRegistry,
)


LOGGER = logging.getLogger("tinyrooms.mc")
RESUME_FILE = "resume.json"


def port_is_available(host: str, port: int) -> bool:
    """Return True when *host*:*port* can be bound right now."""

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def allocate_port(
    host: str = "127.0.0.1", minimum: int = 5000, maximum: int = 5999,
    *, excluded: set[int] | None = None,
) -> int:
    """Find an available TCP port within the configured inclusive bounds."""

    for port in range(minimum, maximum + 1):
        if port in (excluded or set()):
            continue
        if port_is_available(host, port):
            return port
    raise ValueError(f"No available instance port in configured range {minimum}-{maximum}.")


def _endpoint(host: str, port: int) -> str:
    advertised = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    advertised = f"[{advertised}]" if ":" in advertised else advertised
    return f"https://{advertised}:{port}"


def _public_origin(host: str) -> str:
    """Return an HTTPS origin for a hostname without appending a port."""

    advertised = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"https://{advertised}"


def same_origin_base_path(mc_base_path: str, instance_id: str) -> str:
    """Return the public path that routes one instance through the entry origin."""

    return normalize_base_path(f"{mc_base_path}/world/{instance_id}")


def same_origin_client_url(mc_base_path: str, public_host: str, instance_id: str) -> str:
    """Return the same-origin browser URL for one instance."""

    return f"{_public_origin(public_host)}{same_origin_base_path(mc_base_path, instance_id)}/"


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


def _pid_alive(pid: int) -> bool:
    """Return True when *pid* names a live process without signaling it."""

    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259  # STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - a dead handle simply means not alive
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _proc_identity_matches(pid: int, *, instance_id: str, port: int) -> bool:
    """Return True when ``/proc/<pid>/environ`` identifies *instance_id*:*port*.

    Non-Linux platforms cannot verify ownership, so liveness alone is used
    there; Linux always requires the managed-environment match.
    """

    environ = Path(f"/proc/{pid}/environ")
    if not environ.is_file():
        return sys.platform != "linux"
    try:
        entries = environ.read_bytes().split(b"\0")
    except OSError:
        return False
    wanted_id = f"TRSERVER_MC_INSTANCE_ID={instance_id}".encode("utf-8", "ignore")
    wanted_port = f"TRSERVER_PORT={port}".encode("utf-8", "ignore")
    return wanted_id in entries and wanted_port in entries


def _scan_managed_children() -> dict[tuple[str, int], int]:
    """Map ``(instance_id, port)`` to PID for live managed children.

    Only Linux exposes child environments this way. Each candidate costs a
    small read; failures are skipped because other users' processes stay
    unreadable and short-lived processes may vanish mid-scan.
    """

    found: dict[tuple[str, int], int] = {}
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return found
    self_pid = os.getpid()
    for child in proc_root.iterdir():
        if not child.name.isdigit():
            continue
        pid = int(child.name)
        if pid == self_pid:
            continue
        try:
            entries = (child / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        instance_id: str | None = None
        port: int | None = None
        for entry in entries:
            if entry.startswith(b"TRSERVER_MC_INSTANCE_ID="):
                instance_id = entry.partition(b"=")[2].decode("utf-8", "ignore")
            elif entry.startswith(b"TRSERVER_PORT="):
                try:
                    port = int(entry.partition(b"=")[2])
                except ValueError:
                    port = None
        if instance_id and port is not None:
            found.setdefault((instance_id, port), pid)
    return found


class RestoredChildProcess:
    """Signal-based handle for a child that survived a Mission Control restart.

    Spawned children keep running across an ordinary MC restart, but the new
    MC process has no ``subprocess.Popen`` for them. This adapter terminates
    only a PID whose environment still names the expected instance, so PID
    reuse cannot kill an unrelated process.
    """

    def __init__(self, pid: int, *, instance_id: str, port: int) -> None:
        self.pid = pid
        self.stdout = None
        self._instance_id = instance_id
        self._port = port

    def _managed(self) -> bool:
        return _pid_alive(self.pid) and _proc_identity_matches(
            self.pid, instance_id=self._instance_id, port=self._port
        )

    def poll(self) -> int | None:
        """Return None while the managed child is alive, else an exit code."""

        return None if self._managed() else -1

    def terminate(self) -> None:
        """Request a graceful shutdown of the managed child."""

        if self._managed():
            os.kill(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        """Force-kill the managed child."""

        if self._managed():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except AttributeError:  # Windows has no SIGKILL; terminate instead.
                os.kill(self.pid, signal.SIGTERM)

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the child to exit, raising on timeout like ``Popen.wait``."""

        deadline = None if timeout is None else time.monotonic() + timeout
        while self._managed():
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(["restored-child", str(self.pid)], timeout)
            time.sleep(0.05)
        return 0


class Supervisor:
    """Owns spawned child world-server processes."""

    def __init__(
        self,
        config: MCConfig,
        registry: InstanceRegistry,
        audit: McAuditLog,
        *,
        spawn: Callable[..., subprocess.Popen] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._audit = audit
        self._spawn = spawn or subprocess.Popen
        self._on_change = on_change
        self._last_change_error: str | None = None
        self._restore_identities()

    @property
    def route_warning(self) -> str | None:
        """Return the most recent world-map failure, if any."""

        return self._last_change_error

    def _changed(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception as exc:  # noqa: BLE001 - a map failure must not break lifecycle work
            self._last_change_error = str(exc) or type(exc).__name__
            LOGGER.exception("world_map.update_failed")
        else:
            self._last_change_error = None

    def _reserved_ports(self, *, exclude: str | None = None) -> set[int]:
        """Return ports claimed by other instances plus the MC listener."""

        reserved = {
            int(record.spawn_config["port"])
            for record in self._registry.list()
            if record.spawn_config and record.instance_id != exclude
            and record.spawn_config.get("port") is not None
        }
        reserved.add(self._config.port)
        return reserved

    def _choose_port(self, host: str, requested: int | None, reserved: set[int]) -> int:
        """Keep an available requested port, otherwise allocate a replacement."""

        if (
            requested is not None
            and self._config.instance_port_min <= requested <= self._config.instance_port_max
            and requested not in reserved
            and port_is_available(host, requested)
        ):
            return requested
        allocated = allocate_port(
            host,
            self._config.instance_port_min,
            self._config.instance_port_max,
            excluded=reserved,
        )
        if requested is not None and requested != allocated:
            LOGGER.warning(
                json.dumps({
                    "event": "mc.port_reassigned",
                    "requested_port": requested,
                    "port": allocated,
                })
            )
        return allocated

    def _apply_port(self, record: InstanceRecord, port: int) -> None:
        """Update a spawned record and its saved settings for a new port."""

        config = record.spawn_config
        if config is None:
            return
        host = str(config.get("host") or self._config.instance_host)
        config["port"] = port
        record.endpoint = _endpoint(host, port)
        if not self._config.same_origin_worlds:
            client_url = f"{_endpoint(self._config.public_instance_hostname, port)}{record.base_path}"
            config["client_url"] = client_url
            record.client_url = client_url

    def _recover_conflicting_port(self, record: InstanceRecord) -> None:
        """Reassign a saved port that is no longer bindable before respawning."""

        config = record.spawn_config
        if config is None:
            return
        host = str(config.get("host") or self._config.instance_host)
        raw_port = config.get("port")
        try:
            requested = int(raw_port) if raw_port is not None else None
        except (TypeError, ValueError):
            requested = None
        allocated = self._choose_port(host, requested, self._reserved_ports(exclude=record.instance_id))
        if allocated != requested:
            self._apply_port(record, allocated)

    def _write_identity(self, path: Path, instance_id: str, spawn_config: dict[str, object]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "instance_id": instance_id,
            "spawn_config": spawn_config,
        }, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _persist_identity(self, record: InstanceRecord) -> None:
        if record.instance_dir is None or record.spawn_config is None:
            return
        self._write_identity(Path(record.instance_dir) / "instance.json", record.instance_id, record.spawn_config)

    def _adopt_restored_process(
        self,
        instance_id: str,
        config: dict[str, object],
        discovered: dict[tuple[str, int], int] | None = None,
    ) -> RestoredChildProcess | None:
        """Return a signal handle for a child that survived an MC restart.

        Saved PIDs are only trusted when the living process still names this
        instance; legacy identities without a PID fall back to the
        ``/proc`` environment scan so pre-fix deployments become manageable.
        """

        try:
            port = int(config.get("port"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        raw_pid = config.get("pid")
        try:
            saved = int(raw_pid) if raw_pid is not None else None
        except (TypeError, ValueError):
            saved = None
        if saved is not None and _pid_alive(saved) and _proc_identity_matches(
            saved, instance_id=instance_id, port=port
        ):
            return RestoredChildProcess(saved, instance_id=instance_id, port=port)
        if discovered is None:
            discovered = _scan_managed_children()
        found = discovered.get((instance_id, port))
        if found is not None and _pid_alive(found):
            return RestoredChildProcess(found, instance_id=instance_id, port=port)
        return None

    def _record_pid(self, record: InstanceRecord, process: object) -> None:
        """Persist the live child PID so restarts stay manageable after MC exits."""

        config = record.spawn_config
        pid = getattr(process, "pid", None)
        if config is None or not isinstance(pid, int) or pid <= 0:
            return
        config["pid"] = pid
        self._persist_identity(record)

    def _restore_identities(self) -> None:
        discovered: dict[tuple[str, int], int] | None = None
        for path in self._config.instances_path.glob("*/instance.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                instance_id = validate_instance_id(str(data["instance_id"]))
                config = data["spawn_config"]
                if not instance_id or not isinstance(config, dict) or self._registry.get(instance_id):
                    continue
                if self._config.same_origin_worlds:
                    config["host"] = self._config.instance_host
                    config["base_path"] = same_origin_base_path(self._config.base_path, instance_id)
                    config["client_url"] = same_origin_client_url(
                        self._config.base_path, self._config.public_instance_hostname, instance_id
                    )
                    self._write_identity(path, instance_id, config)
                if discovered is None:
                    discovered = _scan_managed_children()
                handle = self._adopt_restored_process(instance_id, config, discovered)
                if handle is not None:
                    config["pid"] = handle.pid
                    self._write_identity(path, instance_id, config)
                record = self._registry.register_spawned(
                    instance_id=instance_id, name=str(config["name"]),
                    endpoint=_endpoint(str(config["host"]), int(config["port"])),
                    instance_dir=str(path.parent), process_handle=handle,
                    spawn_config=config, base_path=str(config.get("base_path") or ""),
                )
                self._registry.set_status(record.instance_id, STATUS_UNREACHABLE)
            except (KeyError, OSError, TypeError, ValueError):
                continue

    def start(
        self,
        *,
        name: str,
        world_path: Path,
        worldstate_path: Path | None = None,
        users_path: Path | None = None,
        host: str | None = None,
        port: int | None = None,
        features: str = "",
        admins: str = "",
        mods: str | None = None,
        actor: str = "mission-control",
        base_path: str | None = None,
        instance_id: str | None = None,
        instance_dir: str | None = None,
        version_path: Path | None = None,
        version_id: str | None = None,
    ) -> InstanceRecord:
        """Spawn a child ``run.py`` and register it with the instance registry."""

        instance_id = validate_instance_id(instance_id or "")
        host = self._config.instance_host if self._config.same_origin_worlds else (host or self._config.instance_host)
        if port is not None and not self._config.instance_port_min <= port <= self._config.instance_port_max:
            raise ValueError("Instance port is outside the configured range.")
        allocated_port = self._choose_port(host, port, self._reserved_ports(exclude=instance_id))
        resolved_dir = Path(instance_dir) if instance_dir else self._config.instances_path / (instance_id or f"mc-{uuid.uuid4().hex[:12]}")
        resolved_dir.mkdir(parents=True, exist_ok=True)
        identity_path = resolved_dir / "instance.json"
        if identity_path.is_file():
            saved_id = validate_instance_id(str(json.loads(identity_path.read_text(encoding="utf-8"))["instance_id"]))
            if instance_id is not None and saved_id != instance_id:
                raise ValueError("Instance directory identity does not match the requested instance id.")
            instance_id = saved_id
        instance_id = validate_instance_id(instance_id or resolved_dir.name) or self._registry.allocate_id()
        resolved_worldstate = Path(worldstate_path) if worldstate_path else resolved_dir / "worldstate.sqlite3"
        resolved_users = Path(users_path) if users_path else self._config.users_path
        if self._config.same_origin_worlds:
            resolved_base_path = same_origin_base_path(self._config.base_path, instance_id)
            client_url = same_origin_client_url(
                self._config.base_path, self._config.public_instance_hostname, instance_id
            )
        else:
            resolved_base_path = normalize_base_path(base_path or "")
            public_host = self._config.public_instance_hostname
            client_url = f"{_endpoint(public_host, allocated_port)}{resolved_base_path}"
        config: dict[str, object] = {
            "instance_id": instance_id,
            "client_url": client_url,
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
            "version_id": version_id or "",
        }
        endpoint = _endpoint(host, allocated_port)
        record = self._registry.register_spawned(
            instance_id=instance_id,
            name=name,
            endpoint=endpoint,
            instance_dir=str(resolved_dir),
            process_handle=None,
            base_path=resolved_base_path,
            spawn_config=config,
        )
        self._persist_identity(record)
        try:
            process = self._spawn_process(config)
        except Exception:
            self._registry.set_status(record.instance_id, STATUS_STOPPED)
            raise
        record.process_handle = process
        self._record_pid(record, process)
        self._capture_output(record, process)
        self._watch_process(record, process)
        self._audit.record(actor, "instance.start", target=record.instance_id, detail={"endpoint": endpoint})
        self._changed()
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
            instance_id=str(config.get("instance_id") or ""),
            client_url=str(config.get("client_url") or ""),
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
        if self._config.instance_certfile is not None and self._config.instance_keyfile is not None:
            command.extend(["--certfile", str(self._config.instance_certfile),
                            "--keyfile", str(self._config.instance_keyfile)])
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
        instance_id: str = "",
        client_url: str = "",
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
        env["TRSERVER_MC_ENDPOINT"] = _endpoint(self._config.host, self._config.port).removeprefix("https://")
        env["TRSERVER_MC_INSTANCE_ID"] = instance_id
        env["TRSERVER_CLIENT_URL"] = client_url
        env["TRSERVER_ENTRY_URL"] = self._config.public_origin
        env["TRSERVER_MC_TOKEN"] = self._config.token
        env["TRSERVER_MC_NAME"] = name
        env["TRSERVER_SHARED_CONTENT_PATH"] = str(self._config.content_root)
        if self._config.same_origin_worlds:
            env["TRSERVER_PUBLIC_ORIGIN"] = _public_origin(self._config.public_instance_hostname)
        else:
            env["TRSERVER_PUBLIC_ORIGIN"] = _endpoint(self._config.public_instance_hostname, port)
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
                    pid = getattr(process, "pid", None)
                    config = record.spawn_config
                    if isinstance(pid, int) and config is not None and config.get("pid") == pid:
                        config["pid"] = None
                        self._persist_identity(record)
                    self._changed()

        threading.Thread(target=_wait, name=f"mc-watch-{record.instance_id}", daemon=True).start()

    def _saved_port_occupied(self, record: InstanceRecord) -> bool:
        """Return True when the record's saved port is held by some process."""

        config = record.spawn_config or {}
        host = str(config.get("host") or self._config.instance_host)
        try:
            port = int(config.get("port"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        return not port_is_available(host, port)

    def stop(self, instance_id: str, *, actor: str = "mission-control") -> bool:
        """Stop a spawned child process.

        Returns False when the record names a live child that this MC
        process cannot signal, so callers do not spawn a duplicate onto a
        new port while the old child keeps serving.
        """

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return False
        process = getattr(record, "process_handle", None)
        if process is None:
            if record.status == STATUS_STOPPED or not self._saved_port_occupied(record):
                self._registry.set_status(instance_id, STATUS_STOPPED)
                self._audit.record(actor, "instance.stop", target=instance_id)
                self._changed()
                return True
            LOGGER.warning(json.dumps({
                "event": "mc.unmanaged_child",
                "instance_id": instance_id,
                "detail": "saved child port is occupied by a process this server cannot signal",
            }))
            return False
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    LOGGER.warning(json.dumps({
                        "event": "mc.child_stop_timeout",
                        "instance_id": instance_id,
                    }))
                    return False
        self._registry.set_status(instance_id, STATUS_STOPPED)
        self._audit.record(actor, "instance.stop", target=instance_id)
        self._changed()
        return True

    def restart(self, instance_id: str, *, actor: str = "mission-control") -> InstanceRecord | None:
        """Stop and respawn a child in place, keeping its id and public route."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        if self._config.same_origin_worlds:
            record.spawn_config["host"] = self._config.instance_host
            record.spawn_config["base_path"] = same_origin_base_path(self._config.base_path, record.instance_id)
            record.spawn_config["client_url"] = same_origin_client_url(
                self._config.base_path, self._config.public_instance_hostname, record.instance_id
            )
        record.spawn_config["instance_id"] = record.instance_id
        record.spawn_config.setdefault("client_url", record.client_url or f"{record.endpoint}{record.base_path}")
        if not self.stop(instance_id, actor=actor):
            LOGGER.warning(json.dumps({
                "event": "mc.restart_refused",
                "instance_id": instance_id,
                "detail": "refusing to respawn while the current child cannot be stopped",
            }))
            return None
        self._recover_conflicting_port(record)
        self._persist_identity(record)
        process = self._spawn_process(dict(record.spawn_config))
        revived = self._registry.revive(instance_id, process_handle=process, instance_dir=record.instance_dir)
        if revived is None:
            return None
        self._record_pid(revived, process)
        self._capture_output(revived, process)
        self._watch_process(revived, process)
        self._audit.record(actor, "instance.restart", target=instance_id)
        self._changed()
        return revived

    def start_existing(self, instance_id: str, *, actor: str = "mission-control") -> InstanceRecord | None:
        """Start a stopped spawned child using its saved settings and identity."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None or record.status != STATUS_STOPPED:
            return None
        self._recover_conflicting_port(record)
        self._persist_identity(record)
        process = self._spawn_process(dict(record.spawn_config))
        revived = self._registry.revive(instance_id, process_handle=process)
        if revived is None:
            return None
        self._record_pid(revived, process)
        self._capture_output(revived, process)
        self._watch_process(revived, process)
        self._audit.record(actor, "instance.start", target=instance_id)
        self._changed()
        return revived

    def change_version(
        self,
        instance_id: str,
        *,
        version_id: str,
        version_path: Path,
        world_path: Path,
        actor: str = "mission-control",
    ) -> InstanceRecord | None:
        """Update a spawned instance's saved checkout/world and apply it."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        record.spawn_config["version_id"] = version_id
        record.spawn_config["version_path"] = str(version_path)
        record.spawn_config["world_path"] = str(world_path)
        self._persist_identity(record)
        self._audit.record(actor, "instance.version", target=instance_id, detail={"version": version_id})
        if record.status != STATUS_STOPPED:
            return self.restart(instance_id, actor=actor)
        self._changed()
        return record

    def rename(self, instance_id: str, name: str, *, actor: str = "mission-control") -> InstanceRecord | None:
        """Rename a spawned child while preserving its direct URL and legacy route."""

        record = self._registry.get(instance_id)
        if record is None or record.spawn_config is None:
            return None
        base_path = record.base_path
        updated = self._registry.rename(instance_id, name, base_path)
        if updated is None:
            return None
        self._persist_identity(updated)
        if updated.status != STATUS_STOPPED:
            if self.restart(instance_id, actor=actor) is None:
                return None
        self._audit.record(actor, "instance.rename", target=instance_id, detail={"name": name, "base_path": base_path})
        return self._registry.get(instance_id)

    def delete(self, instance_id: str, *, actor: str = "mission-control") -> bool:
        """Stop a spawned child and drop it from the registry."""

        record = self._registry.get(instance_id)
        if record is None:
            return False
        self.stop(instance_id, actor=actor)
        self._registry.remove(instance_id)
        if record.instance_dir:
            (Path(record.instance_dir) / "instance.json").unlink(missing_ok=True)
        self._drop_resume_entry(instance_id)
        self._audit.record(actor, "instance.delete", target=instance_id)
        self._changed()
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
                    host=str(entry["host"]) if entry.get("host") else None,
                    port=int(entry["port"]) if entry.get("port") else None,
                    features=str(entry.get("features") or ""),
                    admins=str(entry.get("admins") or ""),
                    mods=entry.get("mods") if isinstance(entry.get("mods"), str) else None,
                    base_path=str(entry.get("base_path") or ""),
                    instance_dir=str(entry["instance_dir"]) if entry.get("instance_dir") else None,
                    version_path=Path(str(entry["version_path"])) if entry.get("version_path") else None,
                    version_id=str(entry["version_id"]) if entry.get("version_id") else None,
                )
                started.append(record.instance_id)
            except (KeyError, OSError, ValueError):
                continue
        self._clear_resume()
        return started
