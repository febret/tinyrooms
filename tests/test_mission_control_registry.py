"""Instance registry upsert, heartbeat, and staleness tests."""

from __future__ import annotations

from datetime import timedelta
import unittest

from server.mission_control.registry import (
    EXTERNAL,
    SPAWNED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    STATUS_UNREACHABLE,
    InstanceRegistry,
)
from server.security import utc_now


def _registration(endpoint: str = "https://127.0.0.1:5000", name: str = "tutorial") -> dict[str, object]:
    return {
        "instance_name": name,
        "endpoint": endpoint,
        "version": "1.0.0",
        "protocol_version": 1,
        "world": {"id": "tutorial", "label": "The Little House"},
        "started_at": utc_now().isoformat(),
    }


class InstanceRegistryTests(unittest.TestCase):
    def test_register_creates_and_updates_by_endpoint(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        first = registry.register(_registration())
        second = registry.register(_registration(name="renamed"))
        self.assertEqual(first.instance_id, second.instance_id)
        self.assertEqual(second.name, "renamed")
        self.assertEqual(second.status, STATUS_RUNNING)
        self.assertEqual(len(registry.list()), 1)

    def test_spawned_pre_registration_is_adopted(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        spawned = registry.register_spawned(
            name="tutorial",
            endpoint="https://127.0.0.1:5000",
            instance_dir="/tmp/inst",
            process_handle=object(),
            spawn_config={},
        )
        adopted = registry.register(_registration())
        self.assertEqual(adopted.instance_id, spawned.instance_id)
        self.assertEqual(adopted.source, SPAWNED)

    def test_heartbeat_updates_and_restores_status(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        record = registry.register(_registration())
        registry.set_status(record.instance_id, STATUS_UNREACHABLE)
        updated = registry.heartbeat(record.instance_id, uptime_seconds=42, users_online=3, world_id="tutorial")
        self.assertEqual(updated.status, STATUS_RUNNING)
        self.assertEqual(updated.users_online, 3)
        self.assertEqual(updated.uptime_seconds, 42)

    def test_heartbeat_unknown_instance(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        self.assertIsNone(registry.heartbeat("missing"))

    def test_evict_stale_marks_unreachable(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=5)
        record = registry.register(_registration())
        stale = (utc_now() - timedelta(seconds=30)).isoformat()
        with registry._lock:  # noqa: SLF001 - direct state setup for the test
            record.last_heartbeat_at = stale
        evicted = registry.evict_stale()
        self.assertIn(record.instance_id, evicted)
        self.assertEqual(registry.get(record.instance_id).status, STATUS_UNREACHABLE)
        snapshot = registry.snapshot(registry.get(record.instance_id))
        self.assertEqual(snapshot["status"], STATUS_UNREACHABLE)

    def test_snapshot_includes_world_and_age(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        record = registry.register(_registration())
        snapshot = registry.snapshot(record)
        self.assertEqual(snapshot["world"], {"id": "tutorial", "label": "The Little House"})
        self.assertEqual(snapshot["source"], EXTERNAL)
        self.assertIsNotNone(snapshot["last_heartbeat_seconds"])

    def test_stopped_status_is_preserved(self) -> None:
        registry = InstanceRegistry(stale_after_seconds=15)
        record = registry.register(_registration())
        registry.set_status(record.instance_id, STATUS_STOPPED)
        self.assertEqual(registry.evict_stale(), [])
        self.assertEqual(registry.snapshot(record)["status"], STATUS_STOPPED)


if __name__ == "__main__":
    unittest.main()
