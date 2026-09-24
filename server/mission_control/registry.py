"""In-memory instance registry with heartbeat tracking and staleness eviction.

Mission control keeps no database: records are rebuilt from registration and
heartbeat traffic, and are dropped on restart by design.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import threading
import uuid

from server.security import utc_now


SPAWNED = "spawned"
EXTERNAL = "external"

STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_UNREACHABLE = "unreachable"
STATUS_STOPPED = "stopped"

LOG_RING_LIMIT = 1000


@dataclass
class InstanceRecord:
    """One managed world-server instance."""

    instance_id: str
    name: str
    endpoint: str
    source: str = EXTERNAL
    token_source: str = "env"
    status: str = STATUS_STARTING
    world_id: str | None = None
    world_label: str | None = None
    version: str | None = None
    protocol_version: int | None = None
    started_at: str | None = None
    registered_at: str | None = None
    last_heartbeat_at: str | None = None
    uptime_seconds: float = 0.0
    users_online: int = 0
    stats_cache: dict[str, object] | None = None
    stats_at: str | None = None
    process_handle: object | None = None
    instance_dir: str | None = None
    spawn_config: dict[str, object] | None = None
    capabilities: list[str] = field(default_factory=list)
    log_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_RING_LIMIT))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class InstanceRegistry:
    """Thread-safe in-memory registry of world-server instances."""

    def __init__(self, *, stale_after_seconds: float = 15.0) -> None:
        self._lock = threading.Lock()
        self._instances: dict[str, InstanceRecord] = {}
        self.stale_after_seconds = stale_after_seconds

    def allocate_id(self) -> str:
        """Return a fresh instance id."""

        return f"mc-{uuid.uuid4().hex[:12]}"

    def get(self, instance_id: str) -> InstanceRecord | None:
        """Return a record by instance id."""

        with self._lock:
            return self._instances.get(instance_id)

    def remove(self, instance_id: str) -> None:
        """Drop a record entirely."""

        with self._lock:
            self._instances.pop(instance_id, None)

    def list(self) -> list[InstanceRecord]:
        """Return every record, sorted by name."""

        with self._lock:
            records = list(self._instances.values())
        return sorted(records, key=lambda record: record.name)

    def register(self, payload: dict[str, object], *, source: str = EXTERNAL, token_source: str = "env") -> InstanceRecord:
        """Upsert an instance from a registration payload.

        Spawned children are matched to their pre-registered record by endpoint;
        otherwise a new external record is created.
        """

        name = str(payload.get("instance_name") or "instance")
        endpoint = str(payload.get("endpoint") or "")
        world = payload.get("world") if isinstance(payload.get("world"), dict) else {}
        with self._lock:
            record = self._find_by_endpoint(endpoint)
            if record is None:
                record = InstanceRecord(
                    instance_id=self.allocate_id(),
                    name=name,
                    endpoint=endpoint,
                    source=source,
                    token_source=token_source,
                )
                self._instances[record.instance_id] = record
            record.name = name
            record.world_id = str(world.get("id")) if world.get("id") else None
            record.world_label = str(world.get("label")) if world.get("label") else None
            record.version = str(payload.get("version")) if payload.get("version") else None
            protocol = payload.get("protocol_version")
            record.protocol_version = int(protocol) if isinstance(protocol, int) else None
            record.started_at = str(payload.get("started_at")) if payload.get("started_at") else None
            record.registered_at = utc_now().isoformat()
            record.last_heartbeat_at = record.registered_at
            record.status = STATUS_RUNNING
            return record

    def _find_by_endpoint(self, endpoint: str) -> InstanceRecord | None:
        if not endpoint:
            return None
        for record in self._instances.values():
            if record.endpoint == endpoint:
                return record
        return None

    def register_spawned(
        self,
        *,
        name: str,
        endpoint: str,
        instance_dir: str,
        process_handle: object,
        spawn_config: dict[str, object],
    ) -> InstanceRecord:
        """Pre-register a spawned child so its logs and lifecycle are tracked."""

        with self._lock:
            record = InstanceRecord(
                instance_id=self.allocate_id(),
                name=name,
                endpoint=endpoint,
                source=SPAWNED,
                token_source="spawned",
                status=STATUS_STARTING,
                process_handle=process_handle,
                instance_dir=instance_dir,
                spawn_config=spawn_config,
            )
            self._instances[record.instance_id] = record
            return record

    def heartbeat(
        self,
        instance_id: str,
        *,
        uptime_seconds: float = 0.0,
        users_online: int = 0,
        world_id: str | None = None,
    ) -> InstanceRecord | None:
        """Record a heartbeat and return the updated record."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is None:
                return None
            record.last_heartbeat_at = utc_now().isoformat()
            record.uptime_seconds = float(uptime_seconds)
            record.users_online = int(users_online)
            if world_id:
                record.world_id = world_id
            if record.status in {STATUS_STARTING, STATUS_UNREACHABLE}:
                record.status = STATUS_RUNNING
            return record

    def set_status(self, instance_id: str, status: str) -> None:
        """Set the status for a record."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is not None:
                record.status = status

    def set_capabilities(self, instance_id: str, capabilities: list[str]) -> None:
        """Store the world-advertised admin capabilities."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is not None:
                record.capabilities = list(capabilities)

    def set_stats(self, instance_id: str, stats: dict[str, object]) -> None:
        """Cache the latest stats payload."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is not None:
                record.stats_cache = stats
                record.stats_at = utc_now().isoformat()

    def append_log(self, instance_id: str, line: str) -> None:
        """Append one captured log line to the per-instance ring."""

        if not line:
            return
        with self._lock:
            record = self._instances.get(instance_id)
            if record is not None:
                record.log_buffer.append(line.rstrip("\n"))

    def logs(self, instance_id: str, limit: int = 200) -> list[str]:
        """Return the newest *limit* captured log lines in order."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is None:
                return []
            return list(record.log_buffer)[-limit:]

    def evict_stale(self) -> list[str]:
        """Mark running records without a recent heartbeat as unreachable."""

        now = utc_now()
        evicted: list[str] = []
        with self._lock:
            for record in self._instances.values():
                if record.status not in {STATUS_RUNNING, STATUS_STARTING}:
                    continue
                last = _parse(record.last_heartbeat_at)
                if last is None:
                    continue
                if (now - last).total_seconds() > self.stale_after_seconds:
                    record.status = STATUS_UNREACHABLE
                    evicted.append(record.instance_id)
        return evicted

    def snapshot(self, record: InstanceRecord) -> dict[str, object]:
        """Serialize a record for the mission-control UI."""

        last = _parse(record.last_heartbeat_at)
        age = None if last is None else round((utc_now() - last).total_seconds(), 1)
        status = record.status
        if status in {STATUS_RUNNING, STATUS_STARTING} and age is not None and age > self.stale_after_seconds:
            status = STATUS_UNREACHABLE
        return {
            "instance_id": record.instance_id,
            "name": record.name,
            "endpoint": record.endpoint,
            "source": record.source,
            "status": status,
            "world": {"id": record.world_id, "label": record.world_label},
            "version": record.version,
            "protocol_version": record.protocol_version,
            "started_at": record.started_at,
            "uptime_seconds": record.uptime_seconds,
            "users_online": record.users_online,
            "last_heartbeat_seconds": age,
            "capabilities": list(record.capabilities),
            "has_stats": record.stats_cache is not None,
        }
