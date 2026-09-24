"""Signed activity result hooks: start cost, validation, and records."""

from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3

from server.content.activities import ActivityDefinition
from server.profiles import AccountRecord
from server.security import utc_now
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class Records:
    """Personal and world best survival times for one activity."""

    personal_best: float | None
    world_best: float | None

    def to_payload(self) -> dict[str, float | None]:
        """Serialize the record pair for commands and the activity bridge."""

        return {"personal_best": self.personal_best, "world_best": self.world_best}


@dataclass(frozen=True, slots=True)
class StartResult:
    """Outcome of starting an activity round."""

    kind: str
    charged: int
    energy: float


@dataclass(frozen=True, slots=True)
class CompleteResult:
    """Outcome of completing an activity round."""

    kind: str
    recorded: bool
    captured: bool
    seconds: float
    records: Records


class ActivityResultService:
    """Charges start costs, validates results, and tracks records.

    ``progression`` is accepted so Milestone 4 can attach rewards without
    changing the call sites; this phase only exposes the ``activity_result``
    task trigger.
    """

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: object,
        stats: object,
        progression: object,
        tasks: object,
        world_id: str,
        definitions: dict[str, ActivityDefinition],
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._progression = progression
        self._tasks = tasks
        self._world_id = world_id
        self._definitions = dict(definitions)

    def _require_definition(self, kind: str) -> ActivityDefinition:
        definition = self._definitions.get(kind)
        if definition is None:
            raise ValueError("Unknown activity.")
        return definition

    @staticmethod
    def _validate_result(result: object) -> tuple[float, bool]:
        if not isinstance(result, dict):
            raise ValueError("That activity result is malformed.")
        seconds_raw = result.get("seconds")
        if isinstance(seconds_raw, bool) or not isinstance(seconds_raw, (int, float)):
            raise ValueError("That activity result is malformed.")
        seconds = float(seconds_raw)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("That activity result is malformed.")
        captured = result.get("captured")
        if not isinstance(captured, bool):
            raise ValueError("That activity result is malformed.")
        return seconds, captured

    def _read_records(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        kind: str,
    ) -> Records:
        personal = connection.execute(
            "SELECT best_seconds FROM world.activity_records WHERE account_id = ? AND activity_kind = ?",
            (account_id, kind),
        ).fetchone()
        world = connection.execute(
            "SELECT MAX(best_seconds) AS best FROM world.activity_records WHERE activity_kind = ?",
            (kind,),
        ).fetchone()
        personal_best = float(personal["best_seconds"]) if personal is not None else None
        world_best = float(world["best"]) if world is not None and world["best"] is not None else None
        return Records(personal_best=personal_best, world_best=world_best)

    @staticmethod
    def _record_best(
        connection: sqlite3.Connection,
        account_id: str,
        kind: str,
        seconds: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO world.activity_records (account_id, activity_kind, best_seconds, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, activity_kind) DO UPDATE SET
                best_seconds = MAX(best_seconds, excluded.best_seconds),
                updated_at = excluded.updated_at
            """,
            (account_id, kind, float(seconds), utc_now().isoformat()),
        )

    def start(self, account: AccountRecord, kind: str) -> StartResult:
        """Charge the activity's start cost and report the round."""

        definition = self._require_definition(kind)
        charged = int(definition.start_cost)
        with self._hub.transaction() as connection:
            if charged:
                self._stats.charge_in_transaction(connection, account.id, charged)
        energy = self._stats.view(account.id).energy
        return StartResult(kind=kind, charged=charged, energy=energy)

    def complete(
        self,
        account: AccountRecord,
        kind: str,
        result: object,
    ) -> CompleteResult:
        """Validate and record a finished round."""

        definition = self._require_definition(kind)
        seconds, captured = self._validate_result(result)
        result_fields = dict(result) if isinstance(result, dict) else {}
        recorded = False
        with self._hub.transaction() as connection:
            if definition.record and captured and seconds >= definition.min_completed_round:
                self._record_best(connection, account.id, kind, seconds)
                recorded = True
            records = self._read_records(connection, account.id, kind)
        self._tasks.record(
            account.id,
            "activity_result",
            {**result_fields, "activity": kind},
        )
        return CompleteResult(
            kind=kind,
            recorded=recorded,
            captured=captured,
            seconds=seconds,
            records=records,
        )

    def records(self, account_id: str, kind: str) -> Records:
        """Return the personal and world record for an activity."""

        self._require_definition(kind)
        with self._hub.locked() as connection:
            return self._read_records(connection, account_id, kind)
