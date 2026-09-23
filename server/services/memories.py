"""Journal memories: generation, manual editing, and monthly aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
import json
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from server.profiles import ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub


MAX_MEMORY_LENGTH = 280


@dataclass(frozen=True, slots=True)
class MemoryView:
    """A serialized journal memory."""

    memory_id: str
    author: str
    source_type: str
    text: str
    tags: tuple[str, ...]
    task_id: str | None
    created_at: str
    editable: bool
    local_date: str

    def to_payload(self) -> dict[str, object]:
        """Serialize the memory for the client."""

        return {
            "memory_id": self.memory_id,
            "author": self.author,
            "source_type": self.source_type,
            "text": self.text,
            "tags": list(self.tags),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "editable": self.editable,
            "local_date": self.local_date,
        }


class MemoryService:
    """Owns immutable game memories and editable manual memories."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_id: str,
        timezone: ZoneInfo,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_id = world_id
        self._timezone = timezone

    def local_date_of(self, iso_timestamp: str) -> str:
        """Return the configured-timezone game date for a stored UTC timestamp."""

        try:
            parsed = datetime.fromisoformat(iso_timestamp)
        except (TypeError, ValueError):
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime_timezone.utc)
        return parsed.astimezone(self._timezone).date().isoformat()

    def local_month_of(self, iso_timestamp: str) -> tuple[int, int] | None:
        """Return the configured-timezone (year, month) for a stored timestamp."""

        local = self.local_date_of(iso_timestamp)
        if not local:
            return None
        year, month, _ = local.split("-")
        return int(year), int(month)

    def current_year_month(self) -> tuple[int, int]:
        """Return the current game (year, month) in the configured timezone."""

        now = utc_now().astimezone(self._timezone)
        return now.year, now.month

    @staticmethod
    def _row_to_view(row: sqlite3.Row, local_date: str) -> MemoryView:
        try:
            raw_tags = json.loads(row["tags_json"])
        except (TypeError, ValueError):
            raw_tags = []
        tags = tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else ()
        return MemoryView(
            memory_id=row["memory_id"],
            author=row["author"],
            source_type=row["source_type"],
            text=row["text"],
            tags=tags,
            task_id=row["task_id"],
            created_at=row["created_at"],
            editable=bool(row["editable"]),
            local_date=local_date,
        )

    def _view_for(self, row: sqlite3.Row) -> MemoryView:
        return self._row_to_view(row, self.local_date_of(row["created_at"]))

    def create_game_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        text: str,
        tags: tuple[str, ...] | list[str],
        *,
        task_id: str | None = None,
    ) -> MemoryView:
        """Insert an immutable game-generated memory inside a transaction."""

        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            raise ValueError("Unknown account.")
        now = utc_now().isoformat()
        memory_id = f"mem:{uuid.uuid4()}"
        tag_list = [str(tag) for tag in tags if str(tag)]
        connection.execute(
            """
            INSERT INTO memories (
                memory_id, account_id, world_id, author, source_type, text,
                tags_json, task_id, created_at, editable
            ) VALUES (?, ?, ?, ?, 'game', ?, ?, ?, ?, 0)
            """,
            (
                memory_id,
                account_id,
                self._world_id,
                account.username_display,
                str(text),
                json.dumps(tag_list),
                task_id,
                now,
            ),
        )
        row = connection.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return self._view_for(row)

    def create_game(
        self,
        account_id: str,
        text: str,
        tags: tuple[str, ...] | list[str],
        *,
        task_id: str | None = None,
    ) -> MemoryView:
        """Insert an immutable game-generated memory."""

        with self._hub.transaction() as connection:
            return self.create_game_in_transaction(connection, account_id, text, tags, task_id=task_id)

    def create_manual(self, account_id: str, text: str) -> MemoryView:
        """Create an editable, author-owned memory from chat text."""

        cleaned = str(text).strip()
        if not cleaned:
            raise ValueError("Write something before saving a memory.")
        if len(cleaned) > MAX_MEMORY_LENGTH:
            raise ValueError(f"Memories can be at most {MAX_MEMORY_LENGTH} characters.")
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            raise ValueError("Unknown account.")
        now = utc_now().isoformat()
        memory_id = f"mem:{uuid.uuid4()}"
        with self._hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, account_id, world_id, author, source_type, text,
                    tags_json, task_id, created_at, editable
                ) VALUES (?, ?, ?, ?, 'manual', ?, '[]', NULL, ?, 1)
                """,
                (memory_id, account_id, self._world_id, account.username_display, cleaned, now),
            )
            row = connection.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return self._view_for(row)

    def _require_owned_manual(self, connection: sqlite3.Connection, account_id: str, memory_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM memories WHERE memory_id = ? AND account_id = ?",
            (memory_id, account_id),
        ).fetchone()
        if row is None:
            raise ValueError("That memory is not in your journal.")
        if row["source_type"] != "manual" or not bool(row["editable"]):
            raise ValueError("Game memories cannot be changed.")
        return row

    def edit_manual(self, account_id: str, memory_id: str, text: str) -> MemoryView:
        """Edit only the owner's own manual memory, never touching task history."""

        cleaned = str(text).strip()
        if not cleaned:
            raise ValueError("A memory cannot be empty.")
        if len(cleaned) > MAX_MEMORY_LENGTH:
            raise ValueError(f"Memories can be at most {MAX_MEMORY_LENGTH} characters.")
        with self._hub.transaction() as connection:
            self._require_owned_manual(connection, account_id, memory_id)
            connection.execute("UPDATE memories SET text = ? WHERE memory_id = ?", (cleaned, memory_id))
            row = connection.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return self._view_for(row)

    def delete_manual(self, account_id: str, memory_id: str) -> None:
        """Delete only the owner's own manual memory, never touching task history."""

        with self._hub.transaction() as connection:
            self._require_owned_manual(connection, account_id, memory_id)
            connection.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))

    def list_month(self, account_id: str, year: int, month: int) -> list[MemoryView]:
        """List the account's memories for one game month, oldest first."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE account_id = ? AND world_id = ? ORDER BY created_at, memory_id",
                (account_id, self._world_id),
            ).fetchall()
        views = [self._view_for(row) for row in rows]
        return [view for view in views if view.local_date[:7] == f"{year:04d}-{month:02d}"]

    def list_for_task(self, account_id: str, task_id: str) -> list[MemoryView]:
        """List memories tagged with a task, newest first."""

        tag = f"task:{task_id}"
        with self._hub.locked() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE account_id = ? AND (task_id = ? OR tags_json LIKE ?)
                ORDER BY created_at DESC, memory_id
                """,
                (account_id, task_id, f'%"{tag}"%'),
            ).fetchall()
        return [self._view_for(row) for row in rows]

    def month_summary(self, account_id: str, year: int, month: int) -> dict[str, object]:
        """Aggregate the account's game-month journal progress."""

        keys = (year * 100) + month
        month_memories = self.list_month(account_id, year, month)
        day_counts: dict[str, int] = {}
        for memory in month_memories:
            day_counts[memory.local_date] = day_counts.get(memory.local_date, 0) + 1
        with self._hub.locked() as connection:
            completed_rows = connection.execute(
                "SELECT completed_at FROM task_progress WHERE account_id = ? AND completed_at IS NOT NULL",
                (account_id,),
            ).fetchall()
            ledger_rows = connection.execute(
                "SELECT payload_json, created_at FROM reward_ledger WHERE account_id = ?",
                (account_id,),
            ).fetchall()
        tasks_completed = 0
        for row in completed_rows:
            local = self.local_date_of(row["completed_at"])
            if local and local[:7] == f"{year:04d}-{month:02d}":
                tasks_completed += 1
        kudos = 0
        for row in ledger_rows:
            local = self.local_date_of(row["created_at"])
            if not local or local[:7] != f"{year:04d}-{month:02d}":
                continue
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            kudos += int(payload.get("kudos", 0) or 0)
        profile = self._profiles.get_user_profile(account_id)
        new_friends = 0
        if profile is not None:
            added = profile.profile.get("friend_added_at")
            if isinstance(added, dict):
                for timestamp in added.values():
                    local = self.local_date_of(str(timestamp))
                    if local and local[:7] == f"{year:04d}-{month:02d}":
                        new_friends += 1
        return {
            "year": year,
            "month": month,
            "key": keys,
            "day_counts": day_counts,
            "memory_count": len(month_memories),
            "tasks_completed": tasks_completed,
            "kudos": kudos,
            "new_friends": new_friends,
        }

    def journal_payload(self, account_id: str, year: int | None = None, month: int | None = None) -> dict[str, object]:
        """Return the memory list and month summary used by bootstrap and commands."""

        current_year, current_month = self.current_year_month()
        target_year = current_year if year is None else int(year)
        target_month = current_month if month is None else int(month)
        return {
            "summary": self.month_summary(account_id, target_year, target_month),
            "memories": [memory.to_payload() for memory in self.list_month(account_id, target_year, target_month)],
        }
