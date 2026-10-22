"""Generate the nginx map that routes same-origin worlds to loopback ports."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from server.mission_control.config import MCConfig
from server.mission_control.registry import SPAWNED, STATUS_STOPPED, InstanceRecord, InstanceRegistry


LOGGER = logging.getLogger("tinyrooms.mc")
_INSTANCE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class WorldMapError(RuntimeError):
    """Raised when the nginx world map cannot be installed or reloaded."""


def render_world_map(records: list[InstanceRecord]) -> str:
    """Render a map from public instance ids to authenticated loopback upstreams."""

    lines = ["map $tinyrooms_world_id $tinyrooms_world_upstream {", '    default "";']
    for record in sorted(records, key=lambda item: item.instance_id):
        if record.source != SPAWNED or record.spawn_config is None or record.status == STATUS_STOPPED:
            continue
        if not _INSTANCE_ID.fullmatch(record.instance_id):
            continue
        try:
            port = int(record.spawn_config.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= port <= 65535:
            continue
        lines.append(f'    {record.instance_id} "https://127.0.0.1:{port}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


class WorldMapManager:
    """Install and reload the generated nginx map when instances change."""

    def __init__(
        self,
        config: MCConfig,
        registry: InstanceRegistry,
        *,
        command_runner: object | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._lock = threading.Lock()
        self._last_content: str | None = None
        self._runner = command_runner

    @property
    def enabled(self) -> bool:
        return bool(
            self._config.same_origin_worlds
            and self._config.world_map_path is not None
            and self._config.world_map_reload_command is not None
        )

    def update(self) -> None:
        """Regenerate and install the map, reloading nginx only after a change."""

        if not self.enabled:
            return
        path = self._config.world_map_path
        assert path is not None
        content = render_world_map(self._registry.list())
        with self._lock:
            if content == self._last_content:
                return
            previous = self._read(path)
            staging = self._write_staging(content)
            try:
                self._install(staging, path)
                self._reload()
            except Exception:
                restore = previous if previous is not None else render_world_map([])
                restore_staging: Path | None = None
                try:
                    restore_staging = self._write_staging(restore)
                    self._install(restore_staging, path)
                    self._reload()
                except Exception:
                    LOGGER.exception("world_map.rollback_failed")
                finally:
                    self._remove(staging)
                    if restore_staging is not None:
                        self._remove(restore_staging)
                raise
            else:
                self._remove(staging)
            self._last_content = content
            LOGGER.info("world_map.updated", extra={"instances": content.count("https://")})

    def _read(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _write_staging(self, content: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._config.instances_path,
            prefix="world-map-",
            suffix=".tmp",
            delete=False,
        )
        try:
            handle.write(content)
            handle.flush()
        finally:
            handle.close()
        staging = Path(handle.name)
        staging.chmod(0o644)
        return staging

    def _remove(self, path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass

    def _run(self, command: object, *, shell: bool = False) -> None:
        if self._runner is not None:
            self._runner(command, shell=shell)  # type: ignore[misc]
            return
        result = subprocess.run(
            command,  # type: ignore[arg-type]
            shell=shell,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise WorldMapError(f"Command failed ({result.returncode}): {detail}")

    def _install(self, staging: Path, target: Path) -> None:
        self._run(["sudo", "-n", "install", "-m", "0644", str(staging), str(target)])

    def _reload(self) -> None:
        command = self._config.world_map_reload_command
        assert command is not None
        self._run(command, shell=True)
