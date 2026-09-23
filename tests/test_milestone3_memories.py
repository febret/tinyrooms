"""Milestone 3 Phase B memory persistence and month aggregation tests."""

from __future__ import annotations

import json
import unittest
from zoneinfo import ZoneInfo

from server.services.friends import FriendsService
from server.services.memories import MemoryService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from server.services.tasks import TaskService
from tests.common import WORLD_ID, ServiceTestCase
from tests.test_milestone3_tasks import make_step, make_task


EASTERN = ZoneInfo("America/New_York")


class MemoryServiceTestCase(ServiceTestCase):
    """Shared fixtures for memory service tests."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID)
        self.memories = MemoryService(self.hub, self.profiles, WORLD_ID, EASTERN)

    def build_tasks(self, definitions):
        """Construct a TaskService that writes game memories."""

        return TaskService(
            self.hub,
            self.profiles,
            self.stats,
            self.progression,
            self.content,
            WORLD_ID,
            definitions,
            EASTERN,
            memories=self.memories,
        )

    def insert_memory(self, account_id, text, created_at, *, source_type="manual", editable=1, tags=()):
        """Insert a memory row with an exact timestamp for boundary tests."""

        with self.hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, account_id, world_id, author, source_type, text,
                    tags_json, task_id, created_at, editable
                ) VALUES (?, ?, ?, 'Tester', ?, ?, ?, NULL, ?, ?)
                """,
                (
                    f"mem:{created_at}:{text[:6]}",
                    account_id,
                    WORLD_ID,
                    source_type,
                    text,
                    json.dumps(list(tags)),
                    created_at,
                    editable,
                ),
            )


class ManualMemoryTests(MemoryServiceTestCase):
    """Manual memories are editable by their owner only; game memories are not."""

    def test_owner_can_edit_and_delete_manual_memory(self) -> None:
        owner = self.create_account("owner")
        other = self.create_account("other")
        memory = self.memories.create_manual(owner.id, "Found a sunflower.")
        with self.assertRaises(ValueError):
            self.memories.edit_manual(other.id, memory.memory_id, "Hijacked")
        with self.assertRaises(ValueError):
            self.memories.delete_manual(other.id, memory.memory_id)
        updated = self.memories.edit_manual(owner.id, memory.memory_id, "Found two sunflowers.")
        self.assertEqual(updated.text, "Found two sunflowers.")
        self.memories.delete_manual(owner.id, memory.memory_id)
        self.assertEqual(self.memories.list_month(owner.id, *self.memories.current_year_month()), [])

class MemoryTaskIsolationTests(MemoryServiceTestCase):
    """Editing or deleting memories never mutates task progress or rewards."""

    def test_memory_edits_leave_task_history_untouched(self) -> None:
        owner = self.create_account("owner")
        tasks = self.build_tasks(
            {"gift": make_task("gift", [make_step("one", "enter_room", match={"room_id": "foyer"})], kudos=5, memory_tags=("gift",))}
        )
        tasks.record(owner.id, "enter_room", {"room_id": "foyer"})
        with self.hub.locked() as connection:
            before = connection.execute(
                "SELECT status, steps_json, reward_operation_id FROM task_progress WHERE account_id = ? AND task_id = 'gift'",
                (owner.id,),
            ).fetchone()
            ledger_before = connection.execute(
                "SELECT COUNT(*) FROM reward_ledger WHERE account_id = ?",
                (owner.id,),
            ).fetchone()[0]
        manual = self.memories.create_manual(owner.id, "A private note.")
        self.memories.edit_manual(owner.id, manual.memory_id, "An edited note.")
        self.memories.delete_manual(owner.id, manual.memory_id)
        with self.hub.locked() as connection:
            after = connection.execute(
                "SELECT status, steps_json, reward_operation_id FROM task_progress WHERE account_id = ? AND task_id = 'gift'",
                (owner.id,),
            ).fetchone()
            ledger_after = connection.execute(
                "SELECT COUNT(*) FROM reward_ledger WHERE account_id = ?",
                (owner.id,),
            ).fetchone()[0]
        self.assertEqual(dict(before), dict(after))
        self.assertEqual(ledger_before, ledger_after)


class TimezoneMonthTests(MemoryServiceTestCase):
    """Month boundaries follow the configured game timezone."""

    def test_memories_near_month_boundary_land_in_the_right_month(self) -> None:
        owner = self.create_account("owner")
        self.insert_memory(owner.id, "Late February", "2026-03-01T02:00:00+00:00")
        self.insert_memory(owner.id, "Early March", "2026-03-01T06:00:00+00:00")
        february = self.memories.list_month(owner.id, 2026, 2)
        march = self.memories.list_month(owner.id, 2026, 3)
        self.assertEqual([memory.text for memory in february], ["Late February"])
        self.assertEqual([memory.text for memory in march], ["Early March"])
        summary = self.memories.month_summary(owner.id, 2026, 2)
        self.assertEqual(summary["day_counts"], {"2026-02-28": 1})
        self.assertEqual(summary["memory_count"], 1)

    def test_month_summary_counts_tasks_kudos_and_friends(self) -> None:
        owner = self.create_account("owner")
        friend = self.create_account("friend")
        FriendsService(self.hub, self.profiles).send_request(owner, friend)
        FriendsService(self.hub, self.profiles).accept_request(friend, owner.id)
        tasks = self.build_tasks(
            {"gift": make_task("gift", [make_step("one", "enter_room", match={"room_id": "foyer"})], kudos=7)}
        )
        tasks.record(owner.id, "enter_room", {"room_id": "foyer"})
        self.insert_memory(owner.id, "A February note", "2026-02-15T12:00:00+00:00")
        with self.hub.transaction() as connection:
            connection.execute(
                "UPDATE task_progress SET completed_at = '2026-02-15T12:00:00+00:00' WHERE account_id = ? AND task_id = 'gift'",
                (owner.id,),
            )
            connection.execute(
                "UPDATE reward_ledger SET created_at = '2026-02-15T12:00:00+00:00' WHERE account_id = ?",
                (owner.id,),
            )
        summary = self.memories.month_summary(owner.id, 2026, 2)
        self.assertEqual(summary["tasks_completed"], 1)
        self.assertEqual(summary["kudos"], 7)
        self.assertIn("2026-02-15", summary["day_counts"])
        current = self.memories.current_year_month()
        current_summary = self.memories.month_summary(owner.id, *current)
        self.assertEqual(current_summary["new_friends"], 1)


if __name__ == "__main__":
    unittest.main()
