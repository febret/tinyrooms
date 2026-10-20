"""Admin summon command tests."""

from __future__ import annotations

import asyncio

from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.outcomes import CommandError
from server.commands.parser import parse_command
from server.connections import SyntheticConnection
from tests.common import Milestone2IntegrationTestCase


class SummonCommandTests(Milestone2IntegrationTestCase):
    """Exercise the admin-only `.summon` command through the runtime."""

    def setUp(self) -> None:
        super().setUp()
        runtime = self.runtime()
        self.admin = runtime.profiles.create_account(
            "admin",
            "password123!",
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        runtime.powers.grant("test", self.admin.id, "admin")

    def _dispatch(self, command: str, *, account=None, room_id: str = "hub"):
        runtime = self.runtime()
        account = account or self.admin
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

    def test_admin_summons_npc_into_current_room(self) -> None:
        runtime = self.runtime()
        outcome = self._dispatch(".summon @peep:molly")

        self.assertEqual(outcome.message, "Molly summoned to hub.")
        self.assertEqual(runtime.rooms.peep_room(runtime.world.peeps["molly"]), "hub")
        self.assertEqual(
            {(pending.room_id, pending.event["type"]) for pending in outcome.room_broadcasts},
            {("playroom", "peep.leave"), ("hub", "peep.enter")},
        )

    def test_summon_rejects_peep_already_in_room(self) -> None:
        with self.assertRaisesRegex(CommandError, "already in that room"):
            self._dispatch(".summon @peep:caretaker", room_id="foyer")

    def test_summon_rejects_unknown_peep(self) -> None:
        with self.assertRaisesRegex(CommandError, "does not exist"):
            self._dispatch(".summon @peep:missing")

    def test_summon_requires_admin_power(self) -> None:
        runtime = self.runtime()
        player = runtime.profiles.create_account(
            "player",
            "password123!",
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        with self.assertRaisesRegex(CommandError, "admin power"):
            self._dispatch(".summon @peep:molly", account=player)

    def test_summon_requires_one_peep_target(self) -> None:
        with self.assertRaisesRegex(CommandError, r"Use '\.summon"):
            self._dispatch(".summon")
        with self.assertRaisesRegex(CommandError, "must use @peep"):
            self._dispatch(".summon @way:exit0")
