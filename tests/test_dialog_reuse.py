"""Dialog reuse and movement-guard integration tests through the live runtime."""

from __future__ import annotations

import asyncio

from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.outcomes import CommandError
from server.commands.parser import parse_command
from server.connections import SyntheticConnection
from tests.common import IntegrationTestCase


class DialogReuseTests(IntegrationTestCase):
    """Exercise dialog navigation reuse and the in-conversation move guard."""

    def _dispatch(self, command: str, *, account=None, room_id: str = "foyer"):
        runtime = self.runtime()
        account = account if account is not None else self.player
        context = build_command_context(
            runtime,
            account=account,
            connection=SyntheticConnection(
                account_id=account.id,
                username=account.username_display,
                room_id=room_id,
            ),
            serialize_user=lambda target: {},
        )
        return asyncio.run(dispatch_command(context, parse_command(command)))

    def setUp(self) -> None:
        super().setUp()
        runtime = self.runtime()
        self.player = runtime.profiles.create_account(
            "dialog-player",
            "password123!",
            runtime.world.id,
            "foyer",
        )
        self.admin = runtime.profiles.create_account(
            "dialog-admin",
            "password123!",
            runtime.world.id,
            "foyer",
        )
        runtime.powers.grant("test", self.admin.id, "admin")

    def test_navigation_choices_work_more_than_once(self) -> None:
        self._dispatch(".talk caretaker")
        first = self._dispatch(".dialog 0")
        self.assertEqual(first.payload["dialog"]["node_id"], "chores")
        back = self._dispatch(".dialog 1")
        self.assertEqual(back.payload["dialog"]["node_id"], "start")
        again = self._dispatch(".dialog 0")
        self.assertEqual(again.payload["dialog"]["node_id"], "chores")

    def test_peep_cannot_leave_while_talked_to(self) -> None:
        runtime = self.runtime()
        self._dispatch(".talk caretaker")
        with self.assertRaisesRegex(CommandError, "in conversation"):
            self._dispatch(".summon @peep:caretaker", account=self.admin, room_id="hub")
        self._dispatch(".dialog_end")
        outcome = self._dispatch(".summon @peep:caretaker", account=self.admin, room_id="hub")
        self.assertIn("summoned", outcome.message)
        self.assertEqual(runtime.rooms.peep_room(runtime.world.peeps["caretaker"]), "hub")

    def test_peep_may_move_when_nobody_is_talking_to_them(self) -> None:
        runtime = self.runtime()
        outcome = self._dispatch(".summon @peep:caretaker", account=self.admin, room_id="hub")
        self.assertIn("summoned", outcome.message)


if __name__ == "__main__":
    import unittest

    unittest.main()
