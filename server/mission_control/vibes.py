"""Read/edit access to vibe scores for the mission-control Vibes Manager."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from server.mission_control.audit import McAuditLog
from server.mission_control.registry import SPAWNED, InstanceRegistry
from server.profiles import ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub


PROFILE_STORE = "profile"


def _open_world_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _has_vibes_table(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'vibes'"
    ).fetchone()
    return row is not None


def _select_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT world_id, source_peep_id, target_peep_id, value, updated_at FROM vibes "
        "ORDER BY world_id, source_peep_id, target_peep_id"
    ).fetchall()


class VibesManager:
    """List and edit vibe rows in the shared profile DB and spawned world DBs."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        registry: InstanceRegistry,
        audit: McAuditLog,
    ) -> None:
        self._hub = hub
        self._registry = registry
        self._audit = audit

    def _source_is_account(self, source_peep_id: str) -> bool:
        """Return whether a source id belongs to a player account."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT id FROM accounts WHERE id = ?", (source_peep_id,)
            ).fetchone()
        return row is not None

    def stores(self) -> list[dict[str, object]]:
        """Return every editable vibe store: profile plus spawned world DBs."""

        stores: list[dict[str, object]] = [
            {"id": PROFILE_STORE, "label": "Shared profile DB", "available": True}
        ]
        for record in self._registry.list():
            if record.source != SPAWNED:
                continue
            spawn_config = record.spawn_config if isinstance(record.spawn_config, dict) else {}
            path = spawn_config.get("worldstate_path")
            available = bool(path) and Path(str(path)).is_file()
            stores.append({
                "id": f"instance:{record.instance_id}",
                "label": f"{record.name} world DB",
                "instance_id": record.instance_id,
                "available": available,
            })
        return stores

    def _world_database(self, store: str) -> Path:
        """Resolve a world store id to its on-disk worldstate database."""

        prefix, _, instance_id = store.partition(":")
        if prefix != "instance" or not instance_id:
            raise ValueError("Unknown vibe store.")
        record = self._registry.get(instance_id)
        if record is None or record.source != SPAWNED:
            raise ValueError("Unknown vibe store.")
        spawn_config = record.spawn_config if isinstance(record.spawn_config, dict) else {}
        raw = spawn_config.get("worldstate_path")
        if not raw or not Path(str(raw)).is_file():
            raise ValueError("The world database is unavailable for this instance.")
        return Path(str(raw))

    def list_rows(self, query: str | None = None, *, limit: int = 200) -> dict[str, object]:
        """Return vibe rows from the profile DB and every reachable world DB."""

        rows: list[dict[str, object]] = []
        warnings: list[str] = []
        with self._hub.locked() as connection:
            for row in _select_rows(connection):
                rows.append(self._row(PROFILE_STORE, "Shared profile DB", dict(row)))
        for store in self.stores():
            if store["id"] == PROFILE_STORE or not store["available"]:
                continue
            try:
                path = self._world_database(str(store["id"]))
                connection = _open_world_database(path)
                try:
                    if not _has_vibes_table(connection):
                        warnings.append(f"{store['label']}: vibes table not found.")
                        continue
                    for row in _select_rows(connection):
                        rows.append(self._row(str(store["id"]), str(store["label"]), dict(row)))
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as exc:
                warnings.append(f"{store['label']}: {type(exc).__name__}.")
        needle = (query or "").strip().casefold()
        self._attach_labels(rows)
        if needle:
            rows = [
                row for row in rows
                if needle in str(row["store_label"]).casefold()
                or needle in str(row["world_id"]).casefold()
                or needle in str(row["source_peep_id"]).casefold()
                or needle in str(row["target_peep_id"]).casefold()
                or needle in str(row.get("source_label") or "").casefold()
                or needle in str(row.get("target_label") or "").casefold()
            ]
        rows.sort(key=lambda row: (str(row["world_id"]), str(row["source_peep_id"]), str(row["target_peep_id"])))
        return {"rows": rows[: max(1, min(limit, 500))], "warnings": warnings}

    def _attach_labels(self, rows: list[dict[str, object]]) -> None:
        """Fill account display names for rows whose peep ids are account ids."""

        ids = sorted({
            str(row[key])
            for row in rows
            for key in ("source_peep_id", "target_peep_id")
            if str(row[key])
        })
        if not ids:
            return
        labels: dict[str, str] = {}
        placeholders = ", ".join("?" for _ in ids)
        with self._hub.locked() as connection:
            for row in connection.execute(
                f"SELECT id, username_display FROM accounts WHERE id IN ({placeholders})",
                tuple(ids),
            ):
                labels[str(row["id"])] = str(row["username_display"])
        for row in rows:
            source = str(row["source_peep_id"])
            target = str(row["target_peep_id"])
            row["source_label"] = labels.get(source, source)
            row["target_label"] = labels.get(target, target)

    @staticmethod
    def _row(store: str, store_label: str, row: dict[str, object]) -> dict[str, object]:
        return {
            "store": store,
            "store_label": store_label,
            "world_id": str(row["world_id"]),
            "source_peep_id": str(row["source_peep_id"]),
            "target_peep_id": str(row["target_peep_id"]),
            "value": int(row["value"]),
            "updated_at": str(row["updated_at"]),
        }

    def edit(
        self,
        actor: str,
        store: str,
        world_id: str,
        source_peep_id: str,
        target_peep_id: str,
        value: int,
    ) -> dict[str, object]:
        """Upsert one vibe row, clamped to the supported range."""

        world = str(world_id or "").strip()
        source = str(source_peep_id or "").strip()
        target = str(target_peep_id or "").strip()
        if not world or not source or not target:
            raise ValueError("world_id, source_peep_id, and target_peep_id are required.")
        if source == target:
            raise ValueError("A vibe cannot target its own source.")
        try:
            amount = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("'value' must be an integer.") from exc
        if not -100 <= amount <= 100:
            raise ValueError("'value' must be between -100 and 100.")
        timestamp = utc_now().isoformat()
        if store == PROFILE_STORE:
            if not self._source_is_account(source):
                raise ValueError("Profile-store vibes must come from a player account.")
        elif self._source_is_account(source):
            raise ValueError("Account vibes belong in the shared profile store.")
        statement = """
            INSERT INTO vibes (world_id, source_peep_id, target_peep_id, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(world_id, source_peep_id, target_peep_id) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """
        params = (world, source, target, amount, timestamp)
        try:
            if store == PROFILE_STORE:
                with self._hub.transaction() as connection:
                    connection.execute(statement, params)
            else:
                path = self._world_database(store)
                connection = _open_world_database(path)
                try:
                    if not _has_vibes_table(connection):
                        raise ValueError("This world database has no vibes table.")
                    connection.execute(statement, params)
                finally:
                    connection.close()
        except (sqlite3.Error, OSError) as exc:
            raise ValueError(f"Could not write that vibe row: {exc}.") from exc
        self._audit.record(
            actor,
            "vibes.edit",
            target=f"{world}/{source}->{target}",
            result="ok",
            detail={"store": store, "world_id": world, "value": amount},
        )
        return {"store": store, "world_id": world, "source_peep_id": source,
                "target_peep_id": target, "value": amount, "updated_at": timestamp}

    def delete(
        self,
        actor: str,
        store: str,
        world_id: str,
        source_peep_id: str,
        target_peep_id: str,
    ) -> None:
        """Delete one vibe row, failing when it does not exist."""

        world = str(world_id or "").strip()
        source = str(source_peep_id or "").strip()
        target = str(target_peep_id or "").strip()
        if not world or not source or not target:
            raise ValueError("world_id, source_peep_id, and target_peep_id are required.")
        if store == PROFILE_STORE:
            if not self._source_is_account(source):
                raise ValueError("Profile-store vibes must come from a player account.")
        elif self._source_is_account(source):
            raise ValueError("Account vibes belong in the shared profile store.")
        statement = "DELETE FROM vibes WHERE world_id = ? AND source_peep_id = ? AND target_peep_id = ?"
        params = (world, source, target)
        try:
            if store == PROFILE_STORE:
                with self._hub.transaction() as connection:
                    cursor = connection.execute(statement, params)
                    if cursor.rowcount == 0:
                        raise ValueError("Unknown vibe row.")
            else:
                path = self._world_database(store)
                connection = _open_world_database(path)
                try:
                    if not _has_vibes_table(connection):
                        raise ValueError("This world database has no vibes table.")
                    cursor = connection.execute(statement, params)
                    if cursor.rowcount == 0:
                        raise ValueError("Unknown vibe row.")
                finally:
                    connection.close()
        except (sqlite3.Error, OSError) as exc:
            raise ValueError(f"Could not delete that vibe row: {exc}.") from exc
        self._audit.record(
            actor,
            "vibes.delete",
            target=f"{world}/{source}->{target}",
            result="ok",
            detail={"store": store, "world_id": world},
        )
