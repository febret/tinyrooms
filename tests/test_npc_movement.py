"""NPC peep movement: exit barriers, persistence, routing, and commands."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest

from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef
from server.behaviors.loader import BehaviorAttachment, BehaviorLoader, BehaviorScript, BehaviorScripts
from server.commands.outcomes import CommandError
from server.commands.parser import ParsedCommand
from server.commands.privileged import npc_move_command
from server.profiles import ProfileRepository
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.dialogs import DialogService
from server.services.npc_movement import resolve_npc_move
from server.services.progression import ProgressionService
from server.services.rooms import RoomService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world


class FakeConnections:
    """Minimal connection registry double for dispatcher tests."""

    def __init__(self) -> None:
        self.rooms: dict[str, str] = {}

    async def set_room(self, account_id: str, room_id: str) -> None:
        self.rooms[account_id] = room_id

    async def get(self, account_id: str) -> None:
        return None

    async def list_room(self, room_id: str) -> list[object]:
        return []


class FakeAudit:
    """Records audit calls without touching the database."""

    def __init__(self) -> None:
        self.entries: list[tuple[object, ...]] = []

    def safe_record(self, *args: object, **kwargs: object) -> None:
        self.entries.append(args)


def make_script(handlers: dict[str, object], script_id: str = "fake") -> BehaviorScript:
    """Build an in-memory behavior module from handler functions."""

    module = ModuleType(script_id)
    for name, handler in handlers.items():
        setattr(module, name, handler)
    return BehaviorScript(script_id=script_id, path=None, module=module)


class NpcMovementTestCase(ServiceTestCase):
    """Shared world, room service, and location store for NPC movement."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.peep_states = NpcPeepStateRepository(self.hub, self.world)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID)
        self.activities = ActivityService(SimpleNamespace(features=frozenset()))
        self.connections = FakeConnections()
        self.rooms = RoomService(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            connections=self.connections,
            card_service=CardService(self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}),
            activities=self.activities,
            world=self.world,
            stats=self.stats,
            peep_states=self.peep_states,
        )

    def build_dispatcher(self, scripts: BehaviorScripts) -> BehaviorDispatcher:
        dialogs = DialogService(
            hub=self.hub,
            profiles=self.profiles,
            stats=self.stats,
            catalog=self.catalog,
            progression=self.progression,
            world=self.world,
        )
        dispatcher = BehaviorDispatcher(
            hub=self.hub,
            profiles=self.profiles,
            stats=self.stats,
            progression=self.progression,
            activities=self.activities,
            catalog=self.catalog,
            dialogs=dialogs,
            connections=self.connections,
            scripts=scripts,
            world=self.world,
            peep_states=self.peep_states,
        )
        dialogs.attach_dispatcher(dispatcher)
        return dispatcher


class ExitBarrierTests(NpcMovementTestCase):
    """The loader parses npc_barrier and the resolver enforces it."""

    def test_loader_parses_npc_barrier(self) -> None:
        playroom = self.world.rooms["playroom"]
        self.assertTrue(playroom.exits["hub"].npc_barrier)
        self.assertFalse(playroom.exits["exit0"].npc_barrier)

    def test_resolve_allows_open_exit_and_blocks_barrier_and_lock(self) -> None:
        molly = self.world.peeps["molly"]
        move = resolve_npc_move(self.world, molly, "playroom", "exit0")
        self.assertEqual(move.destination_room_id, "foyer")
        with self.assertRaises(ValueError):
            resolve_npc_move(self.world, molly, "playroom", "hub")
        foyer = self.world.rooms["foyer"]
        locked_room = replace(
            foyer,
            exits={**foyer.exits, "garden": replace(foyer.exits["garden"], locked=True)},
        )
        locked_world = replace(self.world, rooms={**self.world.rooms, "foyer": locked_room})
        with self.assertRaises(ValueError):
            resolve_npc_move(locked_world, molly, "foyer", "garden")


class RoomServiceMovementTests(NpcMovementTestCase):
    """Moving an NPC updates persistence and both room events."""

    def test_move_npc_persists_and_builds_events(self) -> None:
        result = asyncio.run(self.rooms.move_npc("molly", "exit0"))
        self.assertEqual(result.move.destination_room_id, "foyer")
        self.assertEqual(self.peep_states.room_for("molly"), "foyer")
        self.assertEqual(result.source_event["type"], "peep.leave")
        self.assertEqual(result.destination_event["type"], "peep.enter")
        self.assertEqual(result.destination_event["source_room_id"], "playroom")

    def test_snapshot_reflects_current_room(self) -> None:
        account = self.create_account("ada")
        asyncio.run(self.rooms.move_npc("molly", "exit0"))
        source = asyncio.run(self.rooms.build_snapshot(account, "playroom"))
        destination = asyncio.run(self.rooms.build_snapshot(account, "foyer"))
        self.assertNotIn("molly", {npc["id"] for npc in source["npcs"]})
        self.assertIn("molly", {npc["id"] for npc in destination["npcs"]})

    def test_location_survives_reopen(self) -> None:
        asyncio.run(self.rooms.move_npc("molly", "exit0"))
        root = Path(self.temporary_directory.name)
        reopened = DatabaseHub(root / "profiles.sqlite3", root / "worldstate.sqlite3")
        try:
            locations = NpcPeepStateRepository(reopened, self.world)
            self.assertEqual(locations.room_for("molly"), "foyer")
        finally:
            reopened.close()


class DispatcherMovementTests(NpcMovementTestCase):
    """Behavior intents move NPCs and routing follows the current room."""

    def _scripts(self, handler) -> BehaviorScripts:
        script = make_script({"on_tick": handler})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        return BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )

    def test_move_through_intent_relocates_and_broadcasts(self) -> None:
        script = make_script({"on_tick": lambda context, event: context.move_through("exit0")})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        dispatcher = self.build_dispatcher(scripts)
        result = asyncio.run(
            dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom"))
        )
        self.assertEqual(self.peep_states.room_for("molly"), "foyer")
        self.assertEqual(
            {pending.event["type"] for pending in result.room_broadcasts},
            {"peep.leave", "peep.enter"},
        )
        self.assertEqual(
            {pending.room_id for pending in result.room_broadcasts},
            {"playroom", "foyer"},
        )

    def test_move_through_blocked_by_barrier(self) -> None:
        script = make_script({"on_tick": lambda context, event: context.move_through("hub")})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        dispatcher = self.build_dispatcher(scripts)
        result = asyncio.run(
            dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom"))
        )
        self.assertEqual(self.peep_states.room_for("molly"), "playroom")
        self.assertEqual(result.room_broadcasts, [])

    def test_tick_routing_follows_moved_peep(self) -> None:
        seen: list[str] = []
        scripts = self._scripts(lambda context, event: seen.append(event.room_id))
        dispatcher = self.build_dispatcher(scripts)
        asyncio.run(
            dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom"))
        )
        self.assertEqual(seen, ["playroom"])
        asyncio.run(self.rooms.move_npc("molly", "exit0"))
        asyncio.run(
            dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom"))
        )
        asyncio.run(
            dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="foyer"))
        )
        self.assertEqual(seen, ["playroom", "foyer"])

    def test_tutorial_scripts_load(self) -> None:
        scripts = BehaviorLoader().load_world(self.world)
        self.assertIn("molly", scripts.peep_attachments)

    def test_molly_tick_wanders_through_open_exit(self) -> None:
        scripts = BehaviorLoader().load_world(self.world)
        dispatcher = self.build_dispatcher(scripts)
        module = scripts.scripts[scripts.peep_attachments["molly"].script_id].module
        original = module.random.random
        module.random.random = lambda: 0.0
        try:
            asyncio.run(
                dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom"))
            )
        finally:
            module.random.random = original
        self.assertEqual(self.peep_states.room_for("molly"), "foyer")


class AdminCommandTests(NpcMovementTestCase):
    """The admin .npcgo handler drives the shared room service."""

    def test_npc_move_command(self) -> None:
        account = self.create_account("ada")
        audit = FakeAudit()
        context = SimpleNamespace(rooms=self.rooms, account=account, audit=audit)
        command = ParsedCommand(
            kind="normal",
            name="npcgo",
            args=("@peep:molly", "@way:exit0"),
            raw_text=".npcgo @peep:molly @way:exit0",
        )
        outcome = asyncio.run(npc_move_command(context, command))
        self.assertEqual(self.peep_states.room_for("molly"), "foyer")
        self.assertEqual(len(outcome.room_broadcasts), 2)
        self.assertTrue(audit.entries)

    def test_npc_move_command_rejects_unknown_peep(self) -> None:
        account = self.create_account("bea")
        context = SimpleNamespace(rooms=self.rooms, account=account, audit=FakeAudit())
        command = ParsedCommand(
            kind="normal",
            name="npcgo",
            args=("@peep:ghost", "@way:exit0"),
            raw_text=".npcgo @peep:ghost @way:exit0",
        )
        with self.assertRaises(CommandError):
            asyncio.run(npc_move_command(context, command))


if __name__ == "__main__":
    unittest.main()
