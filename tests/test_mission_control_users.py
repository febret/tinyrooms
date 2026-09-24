"""User manager search, detail, and edit tests against a temp profile DB."""

from __future__ import annotations

import unittest

from server.mission_control.audit import McAuditLog
from server.mission_control.users import UserManager
from tests.common import ServiceTestCase


class UserManagerTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.audit = McAuditLog()
        self.manager = UserManager(self.hub, self.profiles, self.audit)

    def test_search_by_username(self) -> None:
        self.create_account("alice")
        self.create_account("bob")
        results = self.manager.search("ali")
        self.assertEqual([entry["username"] for entry in results], ["alice"])

    def test_search_lists_all(self) -> None:
        self.create_account("alice")
        self.create_account("bob")
        self.assertEqual(len(self.manager.search(None)), 2)

    def test_detail_includes_related_rows(self) -> None:
        account = self.create_account("alice")
        detail = self.manager.detail(account.id)
        self.assertEqual(detail["account"]["username_display"], "alice")
        self.assertIn("profile_card_stacks", detail)
        self.assertEqual(len(detail["profile_card_stacks"]), 4)

    def test_detail_unknown_account(self) -> None:
        self.assertIsNone(self.manager.detail("missing"))

    def test_edit_updates_progress_and_powers(self) -> None:
        account = self.create_account("alice")
        self.manager.edit(
            "operator",
            account.id,
            {
                "level": 3,
                "kudos": 120,
                "bops": 55,
                "shared_energy": 12.5,
                "sticker": "s1.png",
                "initial_sticker_complete": True,
                "powers": ["builder", "moderator"],
            },
        )
        updated = self.reload_account(account)
        self.assertEqual(updated.level, 3)
        self.assertEqual(updated.kudos, 120)
        self.assertEqual(updated.bops, 55)
        self.assertEqual(updated.shared_energy, 12.5)
        self.assertTrue(updated.initial_sticker_complete)
        summary = self.manager.search("alice")[0]
        self.assertEqual(summary["powers"], ["builder", "moderator"])

    def test_edit_mute_state(self) -> None:
        account = self.create_account("alice")
        self.manager.edit("operator", account.id, {"muted": True, "mute_minutes": 30})
        with self.hub.locked() as connection:
            row = connection.execute("SELECT muted_until, muted_by FROM accounts WHERE id = ?", (account.id,)).fetchone()
        self.assertIsNotNone(row["muted_until"])
        self.assertEqual(row["muted_by"], "operator")
        self.manager.edit("operator", account.id, {"muted": False})
        with self.hub.locked() as connection:
            row = connection.execute("SELECT muted_until FROM accounts WHERE id = ?", (account.id,)).fetchone()
        self.assertIsNone(row["muted_until"])

    def test_edit_rejects_unknown_field(self) -> None:
        account = self.create_account("alice")
        with self.assertRaises(ValueError):
            self.manager.edit("operator", account.id, {"username": "bob"})

    def test_edit_rejects_unknown_power(self) -> None:
        account = self.create_account("alice")
        with self.assertRaises(ValueError):
            self.manager.edit("operator", account.id, {"powers": ["wizard"]})

    def test_edits_are_audited(self) -> None:
        account = self.create_account("alice")
        self.manager.edit("operator", account.id, {"level": 2})
        entries = self.audit.entries()
        self.assertEqual(entries[0]["action"], "user.edit")


if __name__ == "__main__":
    unittest.main()
