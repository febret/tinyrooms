"""Tests for global titles: loading, unlocks, selection, and display labels."""

from __future__ import annotations

from server.security import utc_now
from server.services.titles import TitleService
from tests.common import ServiceTestCase


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
        self.assertEqual(len(titles.parts), 26)
        self.assertEqual(len(titles.by_slot("salutation")), 7)
        self.assertEqual(len(titles.by_slot("nickname")), 3)
        self.assertEqual(len(titles.by_slot("suffix")), 16)


class TitleLabelTest(ServiceTestCase):
    def test_full_label_format(self) -> None:
        titles = _make_titles(self)
        label = titles.display_label(
            "Ada",
            {"salutation": "captain", "nickname": "tourfriend", "suffix": "suffix-level-5", "crew_name": "Starling"},
        )
        self.assertEqual(label, 'Captain Ada "Tourfriend" Starling, Adept of the Halls')


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

    def test_serialize_payload_shape(self) -> None:
        account = self.create_account("TitlePayload")
        titles = _make_titles(self)
        payload = titles.serialize_for(account)
        self.assertEqual(len(payload["catalog"]), 26)
        self.assertEqual(payload["unlocked"], [])
        self.assertEqual(payload["selection"]["display_label"], "TitlePayload")
        self.assertEqual(payload["cooked_count"], 0)
        self.assertEqual(payload["taught_count"], 0)
