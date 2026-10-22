"""Durable retirement records for instances removed from Mission Control."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading

from server.mission_control.registry import InstanceRecord
from server.security import utc_now


RETIRED_FILE = "retired.json"
MAX_RECORDS = 500


class RetiredInstanceStore:
    """Persist removed instances and their optional replacement destination."""

    def __init__(self, instances_path: Path) -> None:
        self.path = instances_path / RETIRED_FILE
        self._lock = threading.Lock()

    def _read(self) -> list[dict[str, object]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return []
        records = data.get("instances") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict) and record.get("instance_id")]

    def get(self, instance_id: str | None) -> dict[str, object] | None:
        """Return a retirement record, if the instance was explicitly removed."""

        if not instance_id:
            return None
        with self._lock:
            records = self._read()
        for record in reversed(records):
            if record.get("instance_id") == instance_id:
                return dict(record)
        return None

    def successor(self, instance_id: str | None) -> str | None:
        """Return the operator-designated replacement instance id, if any."""

        record = self.get(instance_id)
        value = record.get("successor_instance_id") if record else None
        return value if isinstance(value, str) and value else None

    def record(
        self,
        record: InstanceRecord,
        *,
        successor_instance_id: str | None = None,
        actor: str = "operator",
    ) -> None:
        """Record an instance removal atomically, preserving recent history."""

        entry: dict[str, object] = {
            "instance_id": record.instance_id,
            "name": record.name,
            "world_id": record.world_id,
            "client_url": record.client_url,
            "retired_at": utc_now().isoformat(),
            "retired_by": actor,
            "successor_instance_id": successor_instance_id,
        }
        with self._lock:
            records = [item for item in self._read() if item.get("instance_id") != record.instance_id]
            records.append(entry)
            records = records[-MAX_RECORDS:]
            self._write(records)

    def _write(self, records: list[dict[str, object]]) -> None:
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix="retired-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"instances": records}, handle, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
