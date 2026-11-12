"""Persistence for directed vibe scores between peeps.

Every pair involving a player is global: it lives in the shared profile
database (``main.vibes``) with ``world_id = ''``, NPC endpoints written as
``"<world_id>:<peep_id>"`` and player endpoints as raw account ids. NPC-to-NPC
pairs stay in the world database (``world.vibes``) scoped by ``world_id``.
"""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3

from server.security import utc_now
from server.state.migrations import DatabaseHub


VIBE_MIN = -100
VIBE_MAX = 100
GLOBAL_WORLD_ID = ""


def clamp_vibe(value: int) -> int:
    """Clamp a vibe score to the supported integer range."""

    return max(VIBE_MIN, min(VIBE_MAX, int(value)))


def _table(scope: str) -> str:
    return "main.vibes" if scope == GLOBAL_WORLD_ID else "world.vibes"


class VibesRepository:
    """Read and update ``vibes`` rows by scope.

    A scope is ``''`` for global rows in ``main.vibes`` or a world id for
    NPC-to-NPC rows in ``world.vibes``.
    """

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    def get(self, scope: str, source_peep_id: str, target_peep_id: str) -> int:
        """Return one directed vibe score, defaulting to zero."""

        with self._hub.locked() as connection:
            row = connection.execute(
                f"SELECT value FROM {_table(scope)} WHERE world_id = ? AND source_peep_id = ? AND target_peep_id = ?",
                (scope, source_peep_id, target_peep_id),
            ).fetchone()
        return int(row["value"]) if row is not None else 0

    def outgoing(self, scope: str, source_peep_id: str) -> dict[str, int]:
        """Return every target and score for one source peep."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                f"SELECT target_peep_id, value FROM {_table(scope)} WHERE world_id = ? AND source_peep_id = ?",
                (scope, source_peep_id),
            ).fetchall()
        return {str(row["target_peep_id"]): int(row["value"]) for row in rows}

    def incoming(self, scope: str, target_peep_id: str) -> dict[str, int]:
        """Return every source and score pointing at one target peep."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                f"SELECT source_peep_id, value FROM {_table(scope)} WHERE world_id = ? AND target_peep_id = ?",
                (scope, target_peep_id),
            ).fetchall()
        return {str(row["source_peep_id"]): int(row["value"]) for row in rows}

    def adjust_many_in_transaction(
        self,
        connection: sqlite3.Connection,
        entries: Iterable[tuple[str, str, str, int]],
    ) -> dict[tuple[str, str, str], int]:
        """Apply ``(scope, source, target, delta)`` deltas in a caller-owned transaction.

        Duplicate pairs accumulate; missing rows start from zero. Returns new
        values keyed by ``(scope, source, target)``.
        """

        grouped: dict[tuple[str, str, str], int] = {}
        for scope, source, target, delta in entries:
            if not source or not target or source == target or int(delta) == 0:
                continue
            key = (scope, source, target)
            grouped[key] = grouped.get(key, 0) + int(delta)
        if not grouped:
            return {}

        updated: dict[tuple[str, str, str], int] = {}
        timestamp = utc_now().isoformat()
        for (scope, source, target), delta in grouped.items():
            table = _table(scope)
            row = connection.execute(
                f"SELECT value FROM {table} WHERE world_id = ? AND source_peep_id = ? AND target_peep_id = ?",
                (scope, source, target),
            ).fetchone()
            current = int(row["value"]) if row is not None else 0
            value = clamp_vibe(current + delta)
            connection.execute(
                f"""
                INSERT INTO {table} (world_id, source_peep_id, target_peep_id, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(world_id, source_peep_id, target_peep_id) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (scope, source, target, value, timestamp),
            )
            updated[(scope, source, target)] = value
        return updated

    def globalize_world_rows(self) -> int:
        """Move ``world.vibes`` rows with a player endpoint into global rows.

        Players are ``main.accounts`` ids; other endpoints become
        ``"<world_id>:<peep_id>"``. Idempotent; on conflicts the latest
        ``updated_at`` wins. Returns the number of moved rows.
        """

        player_rows = """
            FROM world.vibes
            WHERE (source_peep_id IN (SELECT id FROM main.accounts)
                   OR target_peep_id IN (SELECT id FROM main.accounts))
        """
        with self._hub.locked() as connection:
            attached = {str(row["name"]) for row in connection.execute("PRAGMA database_list")}
        if "world" not in attached:
            return 0
        with self._hub.transaction() as connection:
            count = int(connection.execute(f"SELECT COUNT(*) AS n {player_rows}").fetchone()["n"])
            if count:
                connection.execute(
                    f"""
                    INSERT INTO main.vibes (world_id, source_peep_id, target_peep_id, value, updated_at)
                    SELECT '',
                        CASE WHEN source_peep_id IN (SELECT id FROM main.accounts)
                            THEN source_peep_id ELSE world_id || ':' || source_peep_id END,
                        CASE WHEN target_peep_id IN (SELECT id FROM main.accounts)
                            THEN target_peep_id ELSE world_id || ':' || target_peep_id END,
                        value, updated_at
                    {player_rows}
                    ORDER BY updated_at
                    ON CONFLICT(world_id, source_peep_id, target_peep_id) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                        WHERE excluded.updated_at >= vibes.updated_at
                    """
                )
                connection.execute(f"DELETE {player_rows}")
        return count
