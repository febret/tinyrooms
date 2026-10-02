"""Host, process, disk, and install-storage metrics for the mission-control UI.

Standard library only. Linux-specific probes (``/proc``) degrade to ``None`` on
other platforms so the UI can render an em dash instead of failing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import os
import platform
import shutil
import sys
import threading
import time

from server.mission_control.config import MCConfig
from server.protocol import PROTOCOL_VERSION
from server.version import BUILD_VERSION, schema_versions


STORAGE_TTL_SECONDS = 60.0
CPU_SAMPLE_SECONDS = 0.15


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_proc_stat() -> tuple[float, float] | None:
    """Return ``(total_jiffies, idle_jiffies)`` from ``/proc/stat``, if present."""

    text = _read_text("/proc/stat")
    if not text:
        return None
    first = text.splitlines()[0].split()
    if not first or first[0] != "cpu":
        return None
    try:
        values = [float(value) for value in first[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0.0)
    return sum(values), idle


def _cpu_percent() -> tuple[float | None, float | None]:
    """Sample system busy percent and process CPU percent over a short window."""

    system_before = _read_proc_stat()
    process_before = time.process_time()
    wall_before = time.monotonic()
    time.sleep(CPU_SAMPLE_SECONDS)
    system_after = _read_proc_stat()
    process_delta = time.process_time() - process_before
    wall_delta = time.monotonic() - wall_before

    process_percent: float | None = None
    if wall_delta > 0:
        process_percent = round(process_delta / wall_delta * 100.0, 1)

    system_percent: float | None = None
    if system_before is not None and system_after is not None:
        total_delta = system_after[0] - system_before[0]
        idle_delta = system_after[1] - system_before[1]
        if total_delta > 0:
            busy = (total_delta - idle_delta) / total_delta * 100.0
            system_percent = round(max(0.0, min(100.0, busy)), 1)
    return system_percent, process_percent


def _meminfo() -> dict[str, object] | None:
    """Return host memory figures from ``/proc/meminfo``, if present."""

    text = _read_text("/proc/meminfo")
    if not text:
        return None
    values: dict[str, float] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            values[key.strip()] = float(parts[0]) * 1024.0
        except ValueError:
            continue
    total = values.get("MemTotal")
    if not total:
        return None
    available = values.get("MemAvailable", values.get("MemFree", 0.0))
    used = max(0.0, total - available)
    swap_total = values.get("SwapTotal", 0.0)
    swap_used = max(0.0, swap_total - values.get("SwapFree", 0.0))
    return {
        "total": int(total),
        "used": int(used),
        "available": int(available),
        "percent": round(used / total * 100.0, 1),
        "swap_total": int(swap_total),
        "swap_used": int(swap_used),
        "swap_percent": round(swap_used / swap_total * 100.0, 1) if swap_total else None,
    }


def _uptime_seconds() -> float | None:
    text = _read_text("/proc/uptime")
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return None


def _cpu_model() -> str | None:
    text = _read_text("/proc/cpuinfo")
    if text:
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                model = line.partition(":")[2].strip()
                if model:
                    return model
    return platform.processor() or None


def _load_average() -> list[float] | None:
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is None:
        return None
    try:
        return [round(value, 2) for value in getloadavg()]
    except OSError:
        return None


def _kB_field(line: str) -> int | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[1]) * 1024.0)
    except ValueError:
        return None


def _process_memory() -> dict[str, int | None]:
    rss: int | None = None
    vms: int | None = None
    text = _read_text("/proc/self/status")
    if text:
        for line in text.splitlines():
            if line.startswith("VmRSS:"):
                rss = _kB_field(line)
            elif line.startswith("VmSize:"):
                vms = _kB_field(line)
    if rss is None:
        try:
            import resource

            max_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            rss = max_rss * 1024 if sys.platform.startswith("linux") else max_rss
        except (ImportError, OSError, ValueError):
            rss = None
    return {"rss": rss, "vms": vms}


def _directory_size(path: Path) -> tuple[int, bool]:
    """Return ``(bytes, partial)`` for *path*, not following symlinks."""

    total = 0
    partial = False
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        partial = True
        except OSError:
            partial = True
    return total, partial


def collect_storage(install_root: Path) -> dict[str, object]:
    """Return recursive sizes for the top-level entries of *install_root*."""

    entries: list[dict[str, object]] = []
    total = 0
    partial = False
    try:
        with os.scandir(install_root) as iterator:
            children = sorted(iterator, key=lambda entry: entry.name)
    except OSError:
        return {
            "path": str(install_root),
            "total": 0,
            "entries": [],
            "partial": True,
            "cached_at": datetime.now(tz=UTC).isoformat(),
        }

    for child in children:
        is_dir = False
        is_symlink = False
        size = 0
        try:
            is_symlink = child.is_symlink()
            if is_symlink:
                pass
            elif child.is_dir(follow_symlinks=False):
                is_dir = True
                size, entry_partial = _directory_size(Path(child.path))
                partial = partial or entry_partial
            elif child.is_file(follow_symlinks=False):
                size = child.stat(follow_symlinks=False).st_size
            else:
                continue
        except OSError:
            partial = True
        total += size
        entries.append(
            {
                "name": child.name,
                "path": child.path,
                "is_dir": is_dir,
                "symlink": is_symlink,
                "size": size,
            }
        )

    for entry in entries:
        size = int(entry["size"])  # type: ignore[arg-type]
        entry["percent"] = round(size / total * 100.0, 1) if total else 0.0
    entries.sort(key=lambda item: int(item["size"]), reverse=True)  # type: ignore[arg-type]

    return {
        "path": str(install_root),
        "total": total,
        "entries": entries,
        "partial": partial,
        "cached_at": datetime.now(tz=UTC).isoformat(),
    }


class ServerInfoService:
    """Collect host/process/disk metrics and cache the install storage scan."""

    def __init__(self, config: MCConfig, *, started_at: float | None = None) -> None:
        self._config = config
        self._started_at = time.time() if started_at is None else started_at
        self._lock = threading.Lock()
        self._storage: dict[str, object] | None = None
        self._storage_at = 0.0

    @property
    def install_root(self) -> Path:
        return self._config.install_root

    def snapshot(self) -> dict[str, object]:
        """Return host, CPU, memory, process, disk, and config information."""

        system_cpu, process_cpu = _cpu_percent()
        uptime = _uptime_seconds()
        memory = _meminfo()
        process_memory = _process_memory()
        config = self._config

        disk: dict[str, object] | None = None
        try:
            usage = shutil.disk_usage(self.install_root)
            disk = {
                "path": str(self.install_root),
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.used / usage.total * 100.0, 1) if usage.total else None,
            }
        except OSError:
            disk = None

        return {
            "host": {
                "hostname": platform.node(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "executable": sys.executable,
                "cpu_count": os.cpu_count(),
                "cpu_model": _cpu_model(),
                "uptime_seconds": uptime,
                "boot_time": (time.time() - uptime) if uptime is not None else None,
                "load_average": _load_average(),
            },
            "cpu": {
                "system_percent": system_cpu,
                "process_percent": process_cpu,
            },
            "memory": memory,
            "process": {
                "pid": os.getpid(),
                "threads": threading.active_count(),
                "uptime_seconds": round(max(0.0, time.time() - self._started_at), 1),
                "rss": process_memory["rss"],
                "vms": process_memory["vms"],
            },
            "disk": disk,
            "config": {
                "version": BUILD_VERSION,
                "protocol": PROTOCOL_VERSION,
                "schema": schema_versions(),
                "host": config.host,
                "port": config.port,
                "base_path": config.base_path,
                "features": sorted(config.features),
                "actor": config.actor,
                "nginx_managed": config.nginx_conf_path is not None,
                "keepalive_configured": config.keepalive_path is not None,
                "repo_root": str(config.repo_root),
                "content_root": str(config.content_root),
                "install_root": str(self.install_root),
                "users_path": str(config.users_path),
                "instances_path": str(config.instances_path),
                "versions_path": str(config.versions_path),
                "releases_path": str(config.releases_path),
            },
        }

    def storage(self, *, force: bool = False) -> dict[str, object]:
        """Return cached install storage breakdown, rescanning after the TTL."""

        with self._lock:
            now = time.monotonic()
            if force or self._storage is None or (now - self._storage_at) >= STORAGE_TTL_SECONDS:
                self._storage = collect_storage(self.install_root)
                self._storage_at = now
            return self._storage
