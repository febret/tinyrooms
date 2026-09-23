"""Milestone 3 Phase A behavior runtime tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest

from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef, PropRef
from server.behaviors.loader import (
    BehaviorAttachment,
    BehaviorLoader,
    BehaviorScript,
    BehaviorScripts,
)
from server.behaviors.ticker import RoomTicker
from server.content.common import ContentError
from server.content.worlds import WorldDefinition, load_world_definition
from server.profiles import ProfileRepository
from server.services.activities import ActivityService
from server.services.dialogs import DialogService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase


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


def make_script(handlers: dict[str, object], script_id: str = "fake") -> BehaviorScript:
    """Build an in-memory behavior script module from handler functions."""

    module = ModuleType(script_id)
    for name, handler in handlers.items():
        setattr(module, name, handler)
    return BehaviorScript(script_id=script_id, path=None, module=module)


class AsyncServiceTestCase(ServiceTestCase, unittest.IsolatedAsyncioTestCase):
    """Service fixtures plus async test support."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_world_definition(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))

    def build(self, scripts: BehaviorScripts):
        """Construct a dispatcher and dialog service around the fixture world."""

        stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        progression = ProgressionService(self.hub, self.profiles, stats, self.catalog, self.content, WORLD_ID)
        activities = ActivityService(SimpleNamespace(features=frozenset()))
        connections = FakeConnections()
        dialogs = DialogService(
            hub=self.hub,
            profiles=self.profiles,
            stats=stats,
            catalog=self.catalog,
            progression=progression,
            world=self.world,
        )
        dispatcher = BehaviorDispatcher(
            hub=self.hub,
            profiles=self.profiles,
            stats=stats,
            progression=progression,
            activities=activities,
            catalog=self.catalog,
            dialogs=dialogs,
            connections=connections,
            scripts=scripts,
            world=self.world,
        )
        dialogs.attach_dispatcher(dispatcher)
        return SimpleNamespace(dispatcher=dispatcher, dialogs=dialogs, stats=stats, connections=connections)


class DispatchTests(AsyncServiceTestCase):
    """Every typed event reaches the right handler and intent application."""

    async def test_dispatches_every_event_type(self) -> None:
        calls: list[tuple[str, str | None]] = []

        def recorder(context, event):
            calls.append((event.type, event.action))

        script = make_script({f"on_{kind}": recorder for kind in (
            "tick", "enter", "leave", "quick_action", "card_play", "dialog_action", "activity_result"
        )})
        peep_ref = PeepRef(kind="npc", peep_id="molly", account_id=None)
        attachment = BehaviorAttachment(script_id="fake", namespace="peep", instance_id="molly", ref=peep_ref)
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        runtime = self.build(scripts)
        actor = PeepRef(kind="user", peep_id=None, account_id="acct")
        await runtime.dispatcher.dispatch(BehaviorEvent(type="tick", actor=actor, room_id="playroom"))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="enter", actor=actor, room_id="playroom"))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="leave", actor=actor, room_id="playroom"))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="quick_action", actor=actor, target=peep_ref, room_id="playroom", action="pet"))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="card_play", actor=actor, target=peep_ref, room_id="playroom"))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="dialog_action", actor=actor, target=peep_ref, room_id="playroom", data={"peep_id": "molly"}))
        await runtime.dispatcher.dispatch(BehaviorEvent(type="activity_result", actor=actor, room_id="playroom"))
        self.assertEqual(
            [kind for kind, _ in calls],
            ["tick", "enter", "leave", "quick_action", "card_play", "dialog_action", "activity_result"],
        )
        self.assertEqual(calls[3][1], "pet")

    async def test_prop_target_selects_prop_script(self) -> None:
        seen: list[object] = []

        def handler(context, event):
            seen.append(context.target)

        script = make_script({"on_quick_action": handler})
        prop_ref = PropRef(instance_id="vending0", prop_id="vending", room_id="hub")
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={},
            prop_attachments={"vending0": BehaviorAttachment("fake", "prop", "vending0", prop_ref)},
            room_attachments={},
        )
        runtime = self.build(scripts)
        actor = PeepRef(kind="user", peep_id=None, account_id="acct")
        await runtime.dispatcher.dispatch(
            BehaviorEvent(type="quick_action", actor=actor, target=prop_ref, room_id="hub", action="browse")
        )
        self.assertEqual(seen, [prop_ref])

    async def test_feedback_and_counter_intents_apply(self) -> None:
        account = self.create_account("ada")

        def handler(context, event):
            context.feedback("Molly purrs.")
            context.apply_counter("health", -5)

        script = make_script({"on_quick_action": handler})
        peep_ref = PeepRef(kind="npc", peep_id="molly", account_id=None)
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": BehaviorAttachment("fake", "peep", "molly", peep_ref)},
            prop_attachments={},
            room_attachments={},
        )
        runtime = self.build(scripts)
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        result = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="quick_action", actor=actor, target=peep_ref, room_id="playroom", action="pet")
        )
        self.assertFalse(result.rejected)
        self.assertIn("Molly purrs.", result.messages)
        self.assertEqual(runtime.stats.view(account.id).health, 45)


class ErrorContainmentTests(AsyncServiceTestCase):
    """A failing script rejects only its action and rolls back."""

    async def test_handler_error_rolls_back_and_records(self) -> None:
        account = self.create_account("bea")

        def bad(context, event):
            context.apply_counter("health", -25)
            raise RuntimeError("boom")

        def good(context, event):
            context.feedback("fine")

        script = make_script({"on_quick_action": bad})
        other = make_script({"on_quick_action": good}, script_id="other")
        peep_ref = PeepRef(kind="npc", peep_id="molly", account_id=None)
        scripts = BehaviorScripts(
            scripts={"fake": script, "other": other},
            peep_attachments={
                "molly": BehaviorAttachment("fake", "peep", "molly", peep_ref),
                "caretaker": BehaviorAttachment("other", "peep", "caretaker", PeepRef("npc", "caretaker", None)),
            },
            prop_attachments={},
            room_attachments={},
        )
        runtime = self.build(scripts)
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        rejected = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="quick_action", actor=actor, target=peep_ref, room_id="playroom", action="pet")
        )
        self.assertTrue(rejected.rejected)
        self.assertIn("fake", runtime.dispatcher.erroring)
        self.assertEqual(runtime.stats.view(account.id).health, 50)
        caretaker = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="quick_action", actor=actor, target=PeepRef("npc", "caretaker", None), room_id="foyer", action="talk")
        )
        self.assertFalse(caretaker.rejected)
        self.assertIn("fine", caretaker.messages)


class TickerTests(AsyncServiceTestCase):
    """Tick overlap is prevented and slow handlers are tolerated."""

    async def test_slow_tick_does_not_overlap(self) -> None:
        count = 0

        async def slow(context, event):
            nonlocal count
            await asyncio.sleep(0.05)
            count += 1

        script = make_script({"on_tick": slow})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        runtime = self.build(scripts)
        ticker = RoomTicker(dispatcher=runtime.dispatcher, world=self.world, interval=0.01)
        await asyncio.gather(ticker.run_once("playroom"), ticker.run_once("playroom"))
        self.assertEqual(count, 1)

    async def test_run_once_dispatches_room_scripts(self) -> None:
        ticks: list[str] = []

        def handler(context, event):
            ticks.append(event.room_id)

        script = make_script({"on_tick": handler})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        runtime = self.build(scripts)
        ticker = RoomTicker(dispatcher=runtime.dispatcher, world=self.world)
        await ticker.run_once("playroom")
        self.assertEqual(ticks, ["playroom"])


class StatePersistenceTests(unittest.TestCase):
    """Per-instance state survives reopening the database hub."""

    def test_state_persists_across_restart(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profiles.sqlite3"
            world_path = root / "worldstate.sqlite3"
            ensure_profile_database(profile_path)
            ensure_world_database(world_path)
            from server.content.cards import load_card_catalog

            catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
            world = load_world_definition(REPO_ROOT / "worlds" / "tutorial", set(catalog.cards))
            hub = DatabaseHub(profile_path, world_path)
            try:
                result = self._run_tick(hub, world)
                self.assertEqual(result, 1)
            finally:
                hub.close()
            hub = DatabaseHub(profile_path, world_path)
            try:
                result = self._run_tick(hub, world)
                self.assertEqual(result, 2)
            finally:
                hub.close()

    def _run_tick(self, hub: DatabaseHub, world: WorldDefinition) -> int:
        from server.content.cards import load_card_catalog
        from server.content.gameplay import load_gameplay_content

        profiles = ProfileRepository(hub)
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
        content = load_gameplay_content(REPO_ROOT / "data" / "core")

        def handler(context, event):
            context.state["ticks"] = int(context.state.get("ticks", 0)) + 1

        script = make_script({"on_tick": handler})
        attachment = BehaviorAttachment("fake", "peep", "molly", PeepRef("npc", "molly", None))
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": attachment},
            prop_attachments={},
            room_attachments={"playroom": (attachment,)},
        )
        stats = StatsService(hub, profiles, catalog, content, WORLD_ID)
        progression = ProgressionService(hub, profiles, stats, catalog, content, WORLD_ID)
        activities = ActivityService(SimpleNamespace(features=frozenset()))
        dialogs = DialogService(hub=hub, profiles=profiles, stats=stats, catalog=catalog, progression=progression, world=world)
        dispatcher = BehaviorDispatcher(
            hub=hub,
            profiles=profiles,
            stats=stats,
            progression=progression,
            activities=activities,
            catalog=catalog,
            dialogs=dialogs,
            connections=FakeConnections(),
            scripts=scripts,
            world=world,
        )
        asyncio.run(dispatcher.dispatch(BehaviorEvent(type="tick", actor=PeepRef("npc", None, None), room_id="playroom")))
        row = None
        with hub.locked() as connection:
            row = connection.execute(
                "SELECT state_json FROM world.behavior_state WHERE namespace = 'peep' AND instance_id = 'molly'"
            ).fetchone()
        import json

        return int(json.loads(row["state_json"])["ticks"])


class LoaderTests(AsyncServiceTestCase):
    """The loader imports real scripts and rejects missing files."""

    def test_loads_tutorial_scripts_and_builtins(self) -> None:
        scripts = BehaviorLoader().load_world(self.world)
        self.assertIn("molly", scripts.peep_attachments)
        self.assertIn("caretaker", scripts.peep_attachments)
        self.assertTrue(any(script_id.startswith("builtin:") for script_id in scripts.scripts))
        self.assertTrue(scripts.room_attachments["playroom"])

    def test_missing_script_raises(self) -> None:
        ghost = replace(self.world.peeps["molly"], id="ghost", script_name="missing.py")
        world = replace(self.world, peeps={**self.world.peeps, "ghost": ghost})
        with self.assertRaises(ContentError):
            BehaviorLoader().load_world(world)


if __name__ == "__main__":
    unittest.main()
