"""Tests for global titles: loading, unlocks, selection, and display labels."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from server.content.common import ContentError
from server.content.titles import load_titles_content
from server.security import utc_now
from server.services.task_feedback import TaskChange
from server.services.tasks import TaskService
from server.services.titles import TitleService
from tests.common import REPO_ROOT, ServiceTestCase


def _make_titles(test_case: ServiceTestCase) -> TitleService:
    return TitleService(test_case.hub, test_case.profiles, test_case.content)


def _complete_task(test_case: ServiceTestCase, account_id: str, task_id: str) -> None:
    now = utc_now().isoformat()
    with test_case.hub.transaction() as connection:
        connection.execute(
            """
            INSERT INTO task_progress (
                account_id, task_id, world_id, world_label, title, description,
                scope, status, steps_json, steps_meta_json, reward_json,
                memory_tags_json, repeatable, reset_policy, started_at,
                completed_at, definition_revision, reward_operation_id,
                shared_owner_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, task_id, "tutorial", "Tutorial", task_id, "",
                "personal", "completed", "[]", "[]", "{}",
                "[]", 0, None, now,
                now, 1, f"task:{task_id}",
                None,
            ),
        )


class TitleContentTest(ServiceTestCase):
    def test_seed_catalog_loads(self) -> None:
        titles = self.content.titles
        self.assertEqual(len(titles.parts), 24)
        self.assertEqual(len(titles.by_slot("salutation")), 7)
        self.assertEqual(len(titles.by_slot("nickname")), 2)
        self.assertEqual(len(titles.by_slot("suffix")), 15)
        suffix_labels = [part.label for part in titles.by_slot("suffix")]
        self.assertEqual(len(set(suffix_labels)), 15)

    def test_loader_rejects_duplicate_ids(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "titles.yaml"
            path.write_text(
                "salutations:\n"
                "  - id: captain\n"
                "    label: Captain\n"
                "    unlock: {kind: level, level: 3}\n"
                "nicknames:\n"
                "  - id: captain\n"
                "    label: Captain\n"
                "    unlock: {kind: level, level: 3}\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_titles_content(path)

    def test_loader_rejects_unknown_unlock_kind(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "titles.yaml"
            path.write_text(
                "suffixes:\n"
                "  - id: odd\n"
                "    label: Odd One\n"
                "    unlock: {kind: vibes}\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_titles_content(path)


class TitleLabelTest(ServiceTestCase):
    def test_full_label_format(self) -> None:
        titles = _make_titles(self)
        label = titles.display_label(
            "Ada",
            {"salutation": "captain", "nickname": "tourfriend", "suffix": "suffix-level-5", "crew_name": "Starling"},
        )
        self.assertEqual(label, 'Captain Ada "Tourfriend" Starling, Adept of the Halls')

    def test_empty_slots_omit_cleanly(self) -> None:
        titles = _make_titles(self)
        label = titles.display_label(
            "Ada",
            {"salutation": None, "nickname": None, "suffix": None, "crew_name": ""},
        )
        self.assertEqual(label, "Ada")

    def test_nickname_only_format(self) -> None:
        titles = _make_titles(self)
        label = titles.display_label(
            "Ada",
            {"salutation": None, "nickname": "tourfriend", "suffix": None, "crew_name": ""},
        )
        self.assertEqual(label, 'Ada "Tourfriend"')


class TitleUnlockTest(ServiceTestCase):
    def test_level_suffix_unlock_and_select(self) -> None:
        account = self.create_account("TitleLevels")
        titles = _make_titles(self)
        unlocked, _ = titles.sync_unlocked(account.id)
        self.assertNotIn("suffix-level-1", unlocked)
        account = self.set_progress(account, level=5)
        unlocked, newly = titles.sync_unlocked(account.id)
        self.assertIn("suffix-level-5", unlocked)
        self.assertIn("suffix-level-1", unlocked)
        self.assertNotIn("suffix-level-6", unlocked)
        self.assertTrue(newly)
        selection = titles.set_part(account.id, "suffix", "suffix-level-5")
        self.assertEqual(selection["suffix"], "suffix-level-5")
        self.assertEqual(selection["display_label"], "TitleLevels, Adept of the Halls")

    def test_locked_part_rejected(self) -> None:
        account = self.create_account("TitleLocked")
        titles = _make_titles(self)
        with self.assertRaises(ValueError):
            titles.set_part(account.id, "salutation", "captain")
        with self.assertRaises(ValueError):
            titles.set_part(account.id, "suffix", "nope-not-real")

    def test_clearing_slot(self) -> None:
        account = self.create_account("TitleClear")
        account = self.set_progress(account, level=3)
        titles = _make_titles(self)
        titles.set_part(account.id, "salutation", "captain")
        selection = titles.set_part(account.id, "salutation", None)
        self.assertIsNone(selection["salutation"])
        self.assertEqual(selection["display_label"], "TitleClear")

    def test_crew_name_validation(self) -> None:
        account = self.create_account("TitleCrew")
        titles = _make_titles(self)
        selection = titles.set_crew_name(account.id, "Starling")
        self.assertEqual(selection["crew_name"], "Starling")
        self.assertEqual(selection["display_label"], "TitleCrew Starling")
        with self.assertRaises(ValueError):
            titles.set_crew_name(account.id, "x" * 25)
        with self.assertRaises(ValueError):
            titles.set_crew_name(account.id, "Bad;Name!")
        selection = titles.set_crew_name(account.id, "none-thing")
        self.assertEqual(selection["crew_name"], "none-thing")

    def test_cook_counter_unlocks_chef(self) -> None:
        account = self.create_account("TitleChef")
        titles = _make_titles(self)
        last_newly: list[dict[str, object]] = []
        for _ in range(9):
            last_newly = titles.record_cook(account.id)
        self.assertEqual(self.profiles.get_user_profile(account.id).cooked_count, 9)
        unlocked, _ = titles.sync_unlocked(account.id)
        self.assertNotIn("chef", unlocked)
        last_newly = titles.record_cook(account.id)
        self.assertEqual([part["id"] for part in last_newly], ["chef"])
        selection = titles.set_part(account.id, "salutation", "chef")
        self.assertEqual(selection["display_label"], "Chef TitleChef")

    def test_teach_counter_unlocks_teacher(self) -> None:
        account = self.create_account("TitleTeacher")
        titles = _make_titles(self)
        for _ in range(9):
            titles.record_lesson(account.id)
        unlocked, _ = titles.sync_unlocked(account.id)
        self.assertNotIn("teacher", unlocked)
        newly = titles.record_lesson(account.id)
        self.assertEqual([part["id"] for part in newly], ["teacher"])

    def test_serialize_computes_unlocks_without_persisting(self) -> None:
        account = self.create_account("TitleReadOnly")
        titles = _make_titles(self)
        _complete_task(self, account.id, "house-tour")
        payload = titles.serialize_for(account)
        self.assertIn("tourfriend", payload["unlocked"])
        self.assertNotIn("tourfriend", self.profiles.get_user_profile(account.id).unlocked_titles)

    def test_task_completion_unlocks_nickname(self) -> None:
        account = self.create_account("TitleTask")
        titles = _make_titles(self)
        unlocked, _ = titles.sync_unlocked(account.id)
        self.assertNotIn("tourfriend", unlocked)
        _complete_task(self, account.id, "house-tour")
        unlocked, newly = titles.sync_unlocked(account.id)
        self.assertIn("tourfriend", unlocked)
        self.assertEqual([part["id"] for part in newly], ["tourfriend"])
        selection = titles.set_part(account.id, "nickname", "tourfriend")
        self.assertEqual(selection["display_label"], 'TitleTask "Tourfriend"')

    def test_task_feedback_toasts_new_title(self) -> None:
        account = self.create_account("TitleToast")
        titles = _make_titles(self)
        service = TaskService(
            self.hub,
            self.profiles,
            None,
            None,
            self.content,
            "tutorial",
            {},
            ZoneInfo("UTC"),
        )
        service.attach_titles(titles)
        _complete_task(self, account.id, "house-tour")
        changes = [
            TaskChange(
                account_id=account.id,
                task_id="house-tour",
                task_title="A Tour",
                kind="completed",
            )
        ]
        events = service.feedback_events(account.id, changes, room_id="hub")
        self.assertTrue(
            any(event.get("type") == "toast" and "Tourfriend" in str(event.get("text", "")) for event in events),
            f"expected a Tourfriend unlock toast in {events}",
        )

    def test_serialize_payload_shape(self) -> None:
        account = self.create_account("TitlePayload")
        titles = _make_titles(self)
        payload = titles.serialize_for(account)
        self.assertEqual(len(payload["catalog"]), 24)
        self.assertEqual(payload["unlocked"], [])
        self.assertEqual(payload["selection"]["display_label"], "TitlePayload")
        self.assertEqual(payload["cooked_count"], 0)
        self.assertEqual(payload["taught_count"], 0)

    def test_backfill_taught_from_ten_lessons(self) -> None:
        account = self.create_account("TitleBackfill")
        with self.hub.transaction() as connection:
            now = utc_now().isoformat()
            connection.execute(
                """
                INSERT INTO task_progress (
                    account_id, task_id, world_id, world_label, title, description,
                    scope, status, steps_json, steps_meta_json, reward_json,
                    memory_tags_json, repeatable, reset_policy, started_at,
                    completed_at, definition_revision, reward_operation_id,
                    shared_owner_id
                ) VALUES (?, 'ten-lessons', 'scammon-academia', '', '', '', 'personal',
                          'completed', ?, ?, '{}', '[]', 0, NULL, ?, ?, 1, 'task:ten-lessons', NULL)
                """,
                (
                    account.id,
                    json.dumps([{"step_id": "teach-ten", "progress": 10}]),
                    json.dumps([{"step_id": "teach-ten", "title": "t", "trigger": "signal", "amount": 10}]),
                    now,
                    now,
                ),
            )
        titles = _make_titles(self)
        unlocked, _ = titles.sync_unlocked(account.id)
        self.assertIn("teacher", unlocked)
        self.assertIn("mentor", unlocked)
