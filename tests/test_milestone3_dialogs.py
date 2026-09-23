"""Milestone 3 Phase A declarative dialog tests."""

from __future__ import annotations

from dataclasses import replace
import unittest

from server.behaviors.loader import BehaviorLoader
from server.content.common import ContentError
from server.content.gameplay import StatusCondition
from server.content.worlds import (
    DialogChoice,
    DialogDefinition,
    DialogNode,
    _load_dialog,
)
from tests.common import WORLD_ID
from tests.test_milestone1 import RuntimeTestCase, websocket_headers
from tests.test_milestone3_behaviors import AsyncServiceTestCase


def choice(
    index: int,
    label: str,
    *,
    action_id: str | None = None,
    next_node_id: str | None = None,
    end: bool = False,
    when: StatusCondition | None = None,
    script: str | None = None,
    give_card: str | None = None,
    start_task: str | None = None,
    grant: int = 0,
) -> DialogChoice:
    return DialogChoice(
        index=index,
        label=label,
        action_id=action_id or f"start:{index}",
        next_node_id=next_node_id,
        end=end,
        when=when,
        script=script,
        action=None,
        give_card=give_card,
        start_task=start_task,
        grant=grant,
    )


def single_node_dialog(*choices: DialogChoice) -> DialogDefinition:
    return DialogDefinition(
        start_node_id="start",
        nodes={"start": DialogNode(id="start", text="Hello there.", choices=tuple(choices))},
    )


class DialogValidationTests(unittest.TestCase):
    """Load-time dialog validation rules."""

    def test_dangling_next_is_rejected(self) -> None:
        with self.assertRaises(ContentError):
            _load_dialog({"start": {"text": "Hi", "choices": [{"label": "Go", "next": "missing"}]}}, "peep", set())

    def test_missing_start_is_rejected(self) -> None:
        with self.assertRaises(ContentError):
            _load_dialog({"other": {"text": "Hi", "choices": []}}, "peep", set())

    def test_unreachable_node_is_rejected_unless_unused(self) -> None:
        with self.assertRaises(ContentError):
            _load_dialog(
                {"start": {"text": "Hi", "choices": []}, "orphan": {"text": "Hidden", "choices": []}},
                "peep",
                set(),
            )
        dialog = _load_dialog(
            {"start": {"text": "Hi", "choices": []}, "unused_orphan": {"text": "Hidden", "choices": []}},
            "peep",
            set(),
        )
        self.assertIn("unused_orphan", dialog.nodes)

    def test_choice_needs_exactly_one_destination(self) -> None:
        with self.assertRaises(ContentError):
            _load_dialog({"start": {"text": "Hi", "choices": [{"label": "Both", "next": "start", "end": True}]}}, "peep", set())
        with self.assertRaises(ContentError):
            _load_dialog({"start": {"text": "Hi", "choices": [{"label": "Neither"}]}}, "peep", set())

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(ContentError):
            _load_dialog({"start": {"text": "   ", "choices": []}}, "peep", set())


class DialogServiceTests(AsyncServiceTestCase):
    """Dialog branching, conditions, side effects, and idempotency."""

    def runtime_for(self, world=None):
        self.world = world or self.world
        return self.build(BehaviorLoader().load_world(self.world))

    def custom_world(self, dialog: DialogDefinition):
        peep = replace(self.world.peeps["molly"], dialog=dialog)
        return replace(self.world, peeps={**self.world.peeps, "molly": peep})

    async def test_branching_and_back_navigation(self) -> None:
        runtime = self.runtime_for()
        account = self.create_account("ada", room="foyer")
        runtime.dialogs.start(account, "caretaker")
        first = await runtime.dialogs.choose(account, 0)
        self.assertEqual(first.node_id, "chores")
        second = await runtime.dialogs.choose(account, 0)
        self.assertEqual(second.node_id, "clean")
        third = await runtime.dialogs.choose(account, 0)
        self.assertEqual(third.node_id, "start")

    async def test_hidden_choice_is_disabled_and_rejected(self) -> None:
        hidden = choice(0, "Secret", end=True, when=StatusCondition(counter="health", above=1000))
        visible = choice(1, "Hello", end=True)
        runtime = self.runtime_for(self.custom_world(single_node_dialog(hidden, visible)))
        account = self.create_account("bea", room="playroom")
        active = runtime.dialogs.start(account, "molly")
        payload = runtime.dialogs.serialize(active)
        self.assertTrue(payload["choices"][0]["disabled"])
        self.assertFalse(payload["choices"][1]["disabled"])
        with self.assertRaises(ValueError):
            await runtime.dialogs.choose(account, 0)

    async def test_declarative_side_effects_apply_once(self) -> None:
        grant_choice = choice(0, "Take it", next_node_id="done", give_card="smile", grant=5)
        back = choice(0, "Done", action_id="done:0", end=True)
        dialog = DialogDefinition(
            start_node_id="start",
            nodes={
                "start": DialogNode(id="start", text="Take this.", choices=(grant_choice,)),
                "done": DialogNode(id="done", text="Enjoy.", choices=(back,)),
            },
        )
        runtime = self.runtime_for(self.custom_world(dialog))
        account = self.create_account("cam", room="playroom")
        before = self.profiles.get_account_by_id(account.id).kudos
        runtime.dialogs.start(account, "molly")
        result = await runtime.dialogs.choose(account, 0)
        self.assertEqual(result.node_id, "done")
        after = self.profiles.get_account_by_id(account.id)
        self.assertEqual(after.kudos, before + 5)
        self.assertTrue(any(stack.card_def_id == "smile" for stack in self.profiles.list_inventory(account.id, WORLD_ID)))
        duplicate = await runtime.dialogs.choose(account, 0, action_id="start:0")
        self.assertTrue(duplicate.duplicated)
        self.assertEqual(self.profiles.get_account_by_id(account.id).kudos, before + 5)

    async def test_invalid_choice_is_rejected(self) -> None:
        runtime = self.runtime_for()
        account = self.create_account("dee", room="foyer")
        runtime.dialogs.start(account, "caretaker")
        with self.assertRaises(ValueError):
            await runtime.dialogs.choose(account, 99)

    async def test_duplicate_action_id_is_a_no_op(self) -> None:
        runtime = self.runtime_for()
        account = self.create_account("eve", room="foyer")
        runtime.dialogs.start(account, "caretaker")
        first = await runtime.dialogs.choose(account, 0, action_id="start:0")
        self.assertFalse(first.duplicated)
        self.assertEqual(first.node_id, "chores")
        second = await runtime.dialogs.choose(account, 0, action_id="start:0")
        self.assertTrue(second.duplicated)
        self.assertEqual(second.dialog["node_id"], "chores")

    async def test_stale_dialog_after_departure_is_rejected(self) -> None:
        runtime = self.runtime_for()
        account = self.create_account("fay", room="foyer")
        runtime.dialogs.start(account, "caretaker")
        with self.hub.transaction() as connection:
            self.profiles.set_remembered_room(connection, account.id, WORLD_ID, "hub")
        with self.assertRaises(ValueError):
            await runtime.dialogs.choose(account, 0)


class DialogCommandIntegrationTests(RuntimeTestCase):
    """`.talk`, `.dialog`, `.dialog_end`, and departure over the live protocol."""

    def _travel_to_playroom(self, socket) -> None:
        result = self.command(socket, "go-1", ".go @way:exit0")
        self.assertTrue(result["ok"], result)
        snapshot = socket.receive_json()
        self.assertEqual(snapshot["type"], "room.snapshot")
        self.assertEqual(snapshot["room"]["id"], "playroom")

    def test_talk_choose_and_exit(self) -> None:
        credentials = self.create_ready_account("dia")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self._travel_to_playroom(socket)
            talk = self.command(socket, "talk-1", ".talk molly")
            self.assertTrue(talk["ok"], talk)
            self.assertEqual(talk["payload"]["dialog"]["peep_id"], "molly")
            self.assertTrue(talk["payload"]["dialog"]["text"])
            chosen = self.command(socket, "dialog-1", ".dialog 0")
            self.assertTrue(chosen["ok"], chosen)
            self.assertEqual(chosen["payload"]["dialog"]["node_id"], "play")
            ended = self.command(socket, "dialog-2", ".dialog_end")
            self.assertTrue(ended["ok"], ended)
            self.assertIsNone(ended["payload"]["dialog"])

    def test_go_cancels_active_dialog(self) -> None:
        credentials = self.create_ready_account("elo")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self._travel_to_playroom(socket)
            self.assertTrue(self.command(socket, "talk-1", ".talk molly")["ok"])
            moved = self.command(socket, "go-2", ".go @way:exit0")
            self.assertTrue(moved["ok"], moved)
            snapshot = socket.receive_json()
            self.assertEqual(snapshot["type"], "room.snapshot")
            self.assertIsNone(snapshot["room"]["dialog"])
            rejected = self.command(socket, "dialog-2", ".dialog 0")
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["code"], "command_rejected")

    def test_act_dispatches_flavor(self) -> None:
        credentials = self.create_ready_account("gus")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self._travel_to_playroom(socket)
            result = self.command(socket, "act-1", ".act pet molly")
            self.assertTrue(result["ok"], result)
            events = result.get("events", [])
            self.assertTrue(any(event.get("type") == "toast" for event in events), events)

    def test_authored_act_action_is_visible(self) -> None:
        credentials = self.create_ready_account("jay")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.command(socket, "go-1", ".go @way:exit0")["ok"])
            snapshot = socket.receive_json()["room"]
            molly = next(npc for npc in snapshot["npcs"] if npc["id"] == "molly")
            commands = [action["command"] for action in molly["quick_actions"]]
            self.assertIn(".act pet @peep:molly", commands)

    def test_act_targets_prop(self) -> None:
        credentials = self.create_ready_account("hal")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "act-prop-1", ".act browse @prop:vending0")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["message"], "You browse.")

    def test_act_requires_action_and_target(self) -> None:
        credentials = self.create_ready_account("ivy")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            missing = self.command(socket, "act-bad-1", ".act pet")
            self.assertFalse(missing["ok"])
            unknown = self.command(socket, "act-bad-2", ".act pet @peep:ghost")
            self.assertFalse(unknown["ok"])


if __name__ == "__main__":
    unittest.main()
