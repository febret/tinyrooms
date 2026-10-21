"""In-memory instance registry with heartbeat tracking and staleness eviction.

Records are rebuilt from trusted registration traffic and persisted spawned
identities when mission control restarts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import threading
import uuid

from server.config import validate_instance_id, validate_public_url
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

    # Stable destination/restart identity, distinct from the display name and world id.
    # Legacy registrations without an id receive only a transient registry identity.
    instance_id: str
    name: str
    # Management HTTPS origin; client_url may advertise a different browser address.
    endpoint: str
    # Source determines child-process versus cooperative lifecycle control.
    source: str = EXTERNAL
    token_source: str = "env"
    # Heartbeat staleness means unreachable; child exit means stopped, not removal.
    status: str = STATUS_STARTING
    world_id: str | None = None
    world_label: str | None = None
    world_description: str = ""
    world_image: str = ""
    version: str | None = None
    protocol_version: int | None = None
    # World-reported process start, unlike MC's registration/heartbeat receipt times.
    started_at: str | None = None
    # Optional URL prefix retained in saved launches, including legacy routes.
    base_path: str = ""
    client_url: str | None = None
    # Registered world's entry room, used when validating new-account destinations.
    entry_room_id: str | None = None
    registered_at: str | None = None
    last_heartbeat_at: str | None = None
    # Last heartbeat's process age in seconds and live gameplay connection count;
    # these are world-reported samples, not counts of persisted login sessions.
    uptime_seconds: float = 0.0
    users_online: int = 0
    # Account ids reported by the latest heartbeat for cross-world friend presence.
    online_account_ids: tuple[str, ...] = ()
    # Latest /api/mc/stats response, absent until fetched and possibly stale:
    # uptime is seconds; users carry account/username/room; rooms and content
    # counters are loaded counts; version/schema describe the reporting world.
    stats_cache: dict[str, object] | None = None
    stats_at: str | None = None
    # Spawned-only process/runtime location and saved settings for in-place restart.
    # Restored identities can have settings without a live process handle.
    process_handle: object | None = None
    instance_dir: str | None = None
    spawn_config: dict[str, object] | None = None
    # Commands MC permits forwarding; world dispatch still enforces account powers.
    capabilities: list[str] = field(default_factory=list)
    # Per-instance recent child stdout/stderr, bounded and lost on MC restart.
    # External /api/mc/logs tails are polled directly rather than cached here.
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

        Callers authenticate the shared management token before registration.
        Stable identities take precedence over legacy endpoint matching.
        """

        name = str(payload.get("instance_name") or "instance")
        endpoint = str(payload.get("endpoint") or "")
        world = payload.get("world") if isinstance(payload.get("world"), dict) else {}
        instance_id = validate_instance_id(str(payload.get("instance_id") or world.get("instance_id") or ""))
        client_url = validate_public_url(str(payload.get("client_url") or ""), "client_url")
        with self._lock:
            record = self._instances.get(instance_id) if instance_id else self._find_by_endpoint(endpoint)
            if record is None:
                record = InstanceRecord(
                    instance_id=instance_id or self.allocate_id(),
                    name=name,
                    endpoint=endpoint,
                    source=source,
                    token_source=token_source,
                )
                self._instances[record.instance_id] = record
            record.name = name
            record.endpoint = endpoint
            record.world_id = str(world.get("id")) if world.get("id") else None
            record.world_label = str(world.get("label")) if world.get("label") else None
            record.world_description = str(world.get("description") or "")
            record.world_image = str(world.get("image") or "")
            record.version = str(payload.get("version")) if payload.get("version") else None
            protocol = payload.get("protocol_version")
            record.protocol_version = int(protocol) if isinstance(protocol, int) else None
            record.started_at = str(payload.get("started_at")) if payload.get("started_at") else None
            record.base_path = str(payload.get("base_path") or "")
            record.client_url = client_url or record.client_url or f"{endpoint}{record.base_path}"
            entry_room_id = payload.get("entry_room_id") or world.get("entry_room_id")
            record.entry_room_id = str(entry_room_id) if entry_room_id else None
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
        process_handle: object | None,
        spawn_config: dict[str, object],
        base_path: str = "",
        instance_id: str | None = None,
    ) -> InstanceRecord:
        """Pre-register a spawned child so its logs and lifecycle are tracked."""

        with self._lock:
            record = InstanceRecord(
                instance_id=instance_id or self.allocate_id(),
                name=name,
                endpoint=endpoint,
                source=SPAWNED,
                token_source="spawned",
                status=STATUS_STARTING,
                process_handle=process_handle,
                instance_dir=instance_dir,
                spawn_config=spawn_config,
                base_path=base_path,
                client_url=str(spawn_config.get("client_url") or f"{endpoint}{base_path}"),
            )
            self._instances[record.instance_id] = record
            return record

    def revive(self, instance_id: str, *, process_handle: object, instance_dir: str | None = None) -> InstanceRecord | None:
        """Attach a fresh process to an existing record for an in-place restart."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is None:
                return None
            record.process_handle = process_handle
            if instance_dir is not None:
                record.instance_dir = instance_dir
            record.status = STATUS_STARTING
            record.log_buffer.clear()
            return record

    def rename(self, instance_id: str, name: str, base_path: str) -> InstanceRecord | None:
        """Update an instance's display name and public route."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is None:
                return None
            record.name = name
            record.base_path = base_path
            if record.spawn_config is not None:
                record.spawn_config["name"] = name
                record.spawn_config["base_path"] = base_path
            return record

    def heartbeat(
        self,
        instance_id: str,
        *,
        uptime_seconds: float = 0.0,
        users_online: int = 0,
        online_account_ids: list[str] | None = None,
        world_id: str | None = None,
    ) -> InstanceRecord | None:
        """Record a heartbeat and return the updated record."""

        with self._lock:
            record = self._instances.get(instance_id)
            if record is None:
                return None
            record.last_heartbeat_at = utc_now().isoformat()
            record.uptime_seconds = float(uptime_seconds)
            record.online_account_ids = tuple(dict.fromkeys(online_account_ids or ()))
            record.users_online = max(int(users_online), len(record.online_account_ids))
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
        """Serialize a record for the mission-control UI.

        last_heartbeat_seconds is age at serialization, or null before receipt.
        has_stats indicates cache presence, not freshness or world readiness.
        """

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
            "world": {
                "id": record.world_id,
                "label": record.world_label,
                "description": record.world_description,
                "image": record.world_image,
            },
            "version": record.version,
            "protocol_version": record.protocol_version,
            "started_at": record.started_at,
            "base_path": record.base_path,
            "client_url": record.client_url,
            "entry_room_id": record.entry_room_id,
            "uptime_seconds": record.uptime_seconds,
            "users_online": record.users_online,
            "last_heartbeat_seconds": age,
            "capabilities": list(record.capabilities),
            "has_stats": record.stats_cache is not None,
        }
