"""World-local persistence for the school lesson subsystem.

This layer intentionally stores everything in the existing generic world
tables: ``world_meta`` holds durable JSON documents (the generated student
roster and completed-lesson scores), and ``behavior_state`` holds the per-room
live lesson session. No lesson-specific schema is added to the world DB.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from uuid import uuid4

from server.security import utc_now
from server.state.migrations import DatabaseHub


ROSTER_KEY = "lesson.roster"
SCORE_PREFIX = "lesson.score."
SESSION_NAMESPACE = "lesson"


@dataclass(frozen=True, slots=True)
class StudentRecord:
    """A generated student on a grade's roster."""

    student_id: str
    grade: int
    first_name: str
    last_name: str
    favorites: tuple[str, ...]
    tricky: str
    trait: str | None
    avatar: str

    @property
    def label(self) -> str:
        """Return the student's full display name."""

        return f"{self.first_name} {self.last_name}"

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-ready mapping of the student."""

        return {
            "student_id": self.student_id,
            "grade": self.grade,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "favorites": list(self.favorites),
            "tricky": self.tricky,
            "trait": self.trait,
            "avatar": self.avatar,
        }

    @staticmethod
    def from_payload(payload: dict[str, object]) -> "StudentRecord":
        """Rebuild a student from its stored mapping, tolerating bad data."""

        favorites = payload.get("favorites")
        return StudentRecord(
            student_id=str(payload.get("student_id", "")),
            grade=int(payload.get("grade", 1)),
            first_name=str(payload.get("first_name", "")),
            last_name=str(payload.get("last_name", "")),
            favorites=tuple(str(item) for item in favorites if isinstance(item, str))
            if isinstance(favorites, list)
            else (),
            tricky=str(payload.get("tricky", "")),
            trait=str(payload["trait"]) if payload.get("trait") is not None else None,
            avatar=str(payload.get("avatar", "")),
        )


def _decode_json(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class LessonStateRepository:
    """Roster, live session, and score persistence over generic world tables."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    # -- Roster ---------------------------------------------------------------

    def _read_roster(self) -> list[StudentRecord]:
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT value FROM world.world_meta WHERE key = ?", (ROSTER_KEY,)
            ).fetchone()
        if row is None:
            return []
        try:
            raw = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        return [StudentRecord.from_payload(item) for item in raw if isinstance(item, dict)]

    def has_roster(self) -> bool:
        """Return whether any students have been generated."""

        return bool(self._read_roster())

    def count_students(self) -> int:
        """Return the total number of generated students."""

        return len(self._read_roster())

    def all_students(self) -> list[StudentRecord]:
        """Return every generated student, ordered by grade and id."""

        return sorted(self._read_roster(), key=lambda student: (student.grade, student.student_id))

    def roster_for_grade(self, grade: int) -> list[StudentRecord]:
        """Return the students assigned to one grade floor."""

        return [student for student in self.all_students() if student.grade == int(grade)]

    def insert_students(self, students: list[StudentRecord]) -> None:
        """Persist a freshly generated roster, replacing any existing one."""

        payload = json.dumps([student.to_payload() for student in students])
        with self._hub.transaction() as connection:
            connection.execute(
                "DELETE FROM world.world_meta WHERE key = ?", (ROSTER_KEY,)
            )
            connection.execute(
                "INSERT INTO world.world_meta (key, value) VALUES (?, ?)",
                (ROSTER_KEY, payload),
            )

    # -- Live session ---------------------------------------------------------

    def get_session(self, room_id: str) -> dict[str, object] | None:
        """Return the live lesson session document for a room, if any."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT state_json FROM world.behavior_state WHERE namespace = ? AND instance_id = ?",
                (SESSION_NAMESPACE, room_id),
            ).fetchone()
        if row is None:
            return None
        payload = _decode_json(row["state_json"])
        return payload or None

    def save_session(self, connection: sqlite3.Connection, room_id: str, payload: dict[str, object]) -> None:
        """Insert or replace the live lesson session for a room."""

        connection.execute(
            """
            INSERT INTO world.behavior_state (namespace, instance_id, state_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, instance_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (SESSION_NAMESPACE, room_id, json.dumps(payload), utc_now().isoformat()),
        )

    def clear_session(self, connection: sqlite3.Connection, room_id: str) -> None:
        """Remove the live lesson session for a room."""

        connection.execute(
            "DELETE FROM world.behavior_state WHERE namespace = ? AND instance_id = ?",
            (SESSION_NAMESPACE, room_id),
        )

    # -- Scores ---------------------------------------------------------------

    def record_score(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        world_id: str,
        grade: int,
        gpa: float,
        bops: int,
        students: int,
    ) -> None:
        """Append one completed lesson result to the scoreboard."""

        payload = {
            "account_id": account_id,
            "world_id": world_id,
            "grade": int(grade),
            "gpa": round(float(gpa), 3),
            "bops": int(bops),
            "students": int(students),
            "created_at": utc_now().isoformat(),
        }
        key = f"{SCORE_PREFIX}{uuid4().hex}"
        connection.execute(
            "INSERT INTO world.world_meta (key, value) VALUES (?, ?)",
            (key, json.dumps(payload)),
        )

    def _read_scores(self, world_id: str) -> list[dict[str, object]]:
        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT value FROM world.world_meta WHERE key LIKE ?",
                (f"{SCORE_PREFIX}%",),
            ).fetchall()
        scores: list[dict[str, object]] = []
        for row in rows:
            payload = _decode_json(row["value"])
            if payload and payload.get("world_id") == world_id:
                scores.append(payload)
        return scores

    def scoreboard(self, world_id: str, *, limit: int = 20) -> list[dict[str, object]]:
        """Return the top teachers by best GPA across all their lessons."""

        grouped: dict[str, dict[str, object]] = {}
        for score in self._read_scores(world_id):
            account_id = str(score.get("account_id", ""))
            if not account_id:
                continue
            gpa = float(score.get("gpa", 0.0))
            entry = grouped.setdefault(
                account_id,
                {"account_id": account_id, "best_gpa": 0.0, "total_gpa": 0.0, "lessons": 0, "total_bops": 0},
            )
            entry["best_gpa"] = max(float(entry["best_gpa"]), gpa)
            entry["total_gpa"] = float(entry["total_gpa"]) + gpa
            entry["lessons"] = int(entry["lessons"]) + 1
            entry["total_bops"] = int(entry["total_bops"]) + int(score.get("bops", 0))
        ranked = sorted(
            grouped.values(),
            key=lambda entry: (-float(entry["best_gpa"]), -float(entry["total_gpa"]), str(entry["account_id"])),
        )[: max(1, int(limit))]
        return [
            {
                "account_id": str(entry["account_id"]),
                "best_gpa": round(float(entry["best_gpa"]), 3),
                "average_gpa": round(float(entry["total_gpa"]) / max(1, int(entry["lessons"])), 3),
                "lessons": int(entry["lessons"]),
                "total_bops": int(entry["total_bops"]),
            }
            for entry in ranked
        ]

    def teacher_best_gpa(self, account_id: str, world_id: str) -> float | None:
        """Return the account's best recorded GPA in a world, if any."""

        relevant = [float(score.get("gpa", 0.0)) for score in self._read_scores(world_id) if score.get("account_id") == account_id]
        return round(max(relevant), 3) if relevant else None
