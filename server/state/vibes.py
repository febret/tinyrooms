"""Persistence for directed vibe scores between peeps.

Player-sourced vibes live in the profile database so a shared profile DB can
span worlds; NPC-sourced vibes live in the world database. Both tables have the
same shape and are scoped by ``world_id``.
"""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3

from server.security import utc_now
from server.state.migrations import DatabaseHub


VIBE_MIN = -100
VIBE_MAX = 100


def clamp_vibe(value: int) -> int:
    """Clamp a vibe score to the supported integer range."""

    return max(VIBE_MIN, min(VIBE_MAX, int(value)))


class VibesRepository:
    """Read and update ``vibes`` rows in either attached database."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    @staticmethod
    def table(*, world_source: bool) -> str:
        """Return the qualified table for a source kind."""

        return "world.vibes" if world_source else "main.vibes"

    def get(
        self,
        world_id: str,
        source_peep_id: str,
        target_peep_id: str,
        *,
        world_source: bool,
    ) -> int:
        """Return one directed vibe score, defaulting to zero."""

        table = self.table(world_source=world_source)
        with self._hub.locked() as connection:
            row = connection.execute(
                f"SELECT value FROM {table} WHERE world_id = ? AND source_peep_id = ? AND target_peep_id = ?",
                (world_id, source_peep_id, target_peep_id),
            ).fetchone()
        return int(row["value"]) if row is not None else 0

    def outgoing(
        self,
        world_id: str,
        source_peep_id: str,
        *,
        world_source: bool,
    ) -> dict[str, int]:
        """Return every target and score for one source peep."""

        table = self.table(world_source=world_source)
        with self._hub.locked() as connection:
            rows = connection.execute(
                f"SELECT target_peep_id, value FROM {table} WHERE world_id = ? AND source_peep_id = ?",
                (world_id, source_peep_id),
            ).fetchall()
        return {str(row["target_peep_id"]): int(row["value"]) for row in rows}

    def incoming(
        self,
        world_id: str,
        target_peep_id: str,
        *,
        world_source: bool,
    ) -> dict[str, int]:
        """Return every source and score pointing at one target peep."""

        table = self.table(world_source=world_source)
        with self._hub.locked() as connection:
            rows = connection.execute(
                f"SELECT source_peep_id, value FROM {table} WHERE world_id = ? AND target_peep_id = ?",
                (world_id, target_peep_id),
            ).fetchall()
        return {str(row["source_peep_id"]): int(row["value"]) for row in rows}

    def adjust_in_transaction(
        self,
        connection: sqlite3.Connection,
        world_id: str,
        source_peep_id: str,
        target_peep_id: str,
        delta: int,
        *,
        world_source: bool,
    ) -> int:
        """Apply one delta inside a caller-owned transaction and return the new score."""

        return self.adjust_many_in_transaction(
            connection,
            world_id,
            ((source_peep_id, target_peep_id, delta, world_source),),
        )[(source_peep_id, target_peep_id)]

    def adjust_many_in_transaction(
        self,
        connection: sqlite3.Connection,
        world_id: str,
        entries: Iterable[tuple[str, str, int, bool]],
    ) -> dict[tuple[str, str], int]:
        """Apply grouped deltas inside one caller-owned transaction.

        Entries are ``(source, target, delta, world_source)`` tuples. Only
        nonzero deltas need to be supplied; duplicate pairs are accumulated by
        the caller. Missing rows start from zero.
        """

        grouped: dict[tuple[str, str, bool], int] = {}
        for source, target, delta, world_source in entries:
            if not source or not target or source == target or int(delta) == 0:
                continue
            key = (source, target, world_source)
            grouped[key] = grouped.get(key, 0) + int(delta)
        if not grouped:
            return {}

        updated: dict[tuple[str, str], int] = {}
        timestamp = utc_now().isoformat()
        for (source, target, world_source), delta in grouped.items():
            table = self.table(world_source=world_source)
            row = connection.execute(
                f"SELECT value FROM {table} WHERE world_id = ? AND source_peep_id = ? AND target_peep_id = ?",
                (world_id, source, target),
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
                (world_id, source, target, value, timestamp),
            )
            updated[(source, target)] = value
        return updated
