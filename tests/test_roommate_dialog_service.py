"""Dialog extensions: vibe deltas, Bops grants, repeatable chat, settlement hooks."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from server.content.worlds import DialogChoice, DialogDefinition, DialogNode, _parse_dialog_choice
from server.services.dialogs import DialogService


def make_choice(node_id, index, label, **overrides):
    values = {
        "index": index,
        "label": label,
        "action_id": f"{node_id}:{index}",
        "next_node_id": None,
        "end": True,
        "when": None,
        "script": None,
        "action": None,
        "give_card": None,
        "start_task": None,
        "grant": 0,
        "vibe_delta": 0,
        "grant_bops": 0,
        "repeatable": False,
    }
    values.update(overrides)
    return DialogChoice(**values)


class FakeProgression:
    def __init__(self) -> None:
        self.grants: list[dict] = []
        self.entries: set[tuple[str, str]] = set()

    def has_ledger_entry(self, connection, account_id, ledger_key) -> bool:
        del connection
        return (account_id, ledger_key) in self.entries

    def grant_in_transaction(self, connection, account_id, *, kudos=0, bops=0, cards=(), ledger_key=None, kind="reward"):
        del connection, cards, kind
        if ledger_key is not None:
            self.entries.add((account_id, ledger_key))
        self.grants.append({"account": account_id, "kudos": kudos, "bops": bops})
        return True


class FakeVibes:
    def __init__(self) -> None:
        self.adjustments: list[tuple[str, str, int]] = []

    def adjust(self, source, target, delta) -> int:
        self.adjustments.append((source, target, int(delta)))
        return int(delta)


class FakeStats:
    def view(self, account_id):
        del account_id
        return SimpleNamespace(payload=lambda: {})


class DialogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.common import ServiceTestCase

        self.case = ServiceTestCase(methodName="run")
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.progression = FakeProgression()
        self.vibes = FakeVibes()
        self.peep = SimpleNamespace(id="ttnpc:one", room_id="hub", label="Wren", dialog=None)
        self.world = SimpleNamespace(
            id="tinytown",
            peeps={"ttnpc:one": self.peep},
            rooms={"hub": True},
            entry_room_id="hub",
        )
        self.account = SimpleNamespace(id="account-1")
        profiles = SimpleNamespace(
            get_user_profile=lambda account_id: SimpleNamespace(remembered_room="hub"),
        )
        self.dialogs = DialogService(
            hub=self.case.hub,
            profiles=profiles,
            stats=FakeStats(),
            catalog=SimpleNamespace(cards={}),
            progression=self.progression,
            world=self.world,
            tasks=None,
            peep_states=None,
            vibes=self.vibes,
        )
        self.hook_calls: list[tuple[str, str]] = []
        self.dialogs.attach_side_effect_hook(
            lambda account, peep_id, choice: self.hook_calls.append((peep_id, choice.action or ""))
        )

    def use_dialog(self, nodes: dict[str, DialogNode], start="start") -> None:
        self.peep.dialog = DialogDefinition(start_node_id=start, nodes=nodes)

    def test_vibe_choice_adjusts_both_directions_and_runs_hook(self) -> None:
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(
                        make_choice("start", 0, "Cheers!", next_node_id=None, end=True, vibe_delta=2,
                                    action="tinytown_claim:x:1:0"),
                    ),
                )
            }
        )
        import asyncio

        self.dialogs.start(self.account, "ttnpc:one")
        result = asyncio.run(self.dialogs.choose(self.account, 0))
        self.assertFalse(result.duplicated)
        self.assertIn(("ttnpc:one", self.account.id, 2), self.vibes.adjustments)
        self.assertIn((self.account.id, "ttnpc:one", 2), self.vibes.adjustments)
        self.assertEqual(self.hook_calls, [("ttnpc:one", "tinytown_claim:x:1:0")])

    def test_bops_grant_flows_through_progression(self) -> None:
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(make_choice("start", 0, "Share?", next_node_id=None, end=True, grant_bops=9),),
                )
            }
        )
        import asyncio

        self.dialogs.start(self.account, "ttnpc:one")
        asyncio.run(self.dialogs.choose(self.account, 0))
        self.assertEqual(self.progression.grants[-1]["bops"], 9)

    def test_navigation_reuses_freely_within_one_conversation(self) -> None:
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(make_choice("start", 0, "Back and forth.", next_node_id="start", end=False),),
                )
            }
        )
        import asyncio

        async def twice():
            self.dialogs.start(self.account, "ttnpc:one")
            first = await self.dialogs.choose(self.account, 0)
            second = await self.dialogs.choose(self.account, 0)
            return first, second

        first, second = asyncio.run(twice())
        self.assertFalse(first.duplicated)
        self.assertFalse(second.duplicated)
        self.assertEqual(self.progression.entries, set())
        self.assertEqual(self.vibes.adjustments, [])

    def test_reward_replay_suppresses_grant_but_still_navigates(self) -> None:
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(
                        make_choice("start", 0, "Grant, then onward.", next_node_id="again", end=False,
                                    grant_bops=9),
                    ),
                ),
                "again": DialogNode(
                    id="again",
                    text="Again.",
                    choices=(make_choice("again", 0, "Head back.", next_node_id="start", end=False),),
                ),
            }
        )
        import asyncio

        self.dialogs.start(self.account, "ttnpc:one")
        first = asyncio.run(self.dialogs.choose(self.account, 0))
        self.assertFalse(first.duplicated)
        self.assertEqual(first.node_id, "again")
        asyncio.run(self.dialogs.choose(self.account, 0))
        second = asyncio.run(self.dialogs.choose(self.account, 0))
        self.assertTrue(second.duplicated)
        self.assertEqual(second.node_id, "again")
        bops_grants = [grant["bops"] for grant in self.progression.grants if grant["bops"]]
        self.assertEqual(bops_grants, [9])

    def test_vibe_applies_once_per_session_but_reopens_reset(self) -> None:
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(
                        make_choice("start", 0, "Tell me.", next_node_id="start", end=False, vibe_delta=1),
                    ),
                )
            }
        )
        import asyncio

        async def session():
            self.dialogs.start(self.account, "ttnpc:one")
            first = await self.dialogs.choose(self.account, 0)
            second = await self.dialogs.choose(self.account, 0)
            return first, second

        first, second = asyncio.run(session())
        self.assertFalse(first.duplicated)
        self.assertFalse(second.duplicated)
        self.assertEqual(len(self.vibes.adjustments), 2)
        self.dialogs.end(self.account.id, "reopen")
        asyncio.run(session())
        self.assertEqual(len(self.vibes.adjustments), 4)

    def test_open_session_query_tracks_peeps(self) -> None:
        self.assertFalse(self.dialogs.has_open_session("ttnpc:one"))
        self.use_dialog(
            {
                "start": DialogNode(
                    id="start",
                    text="Hi.",
                    choices=(make_choice("start", 0, "Bye.", next_node_id=None, end=True),),
                )
            }
        )
        self.dialogs.start(self.account, "ttnpc:one")
        self.assertTrue(self.dialogs.has_open_session("ttnpc:one"))
        self.assertEqual([active.peep_id for active in self.dialogs.sessions_for_peep("ttnpc:one")],
                         ["ttnpc:one"])
        self.dialogs.end(self.account.id, "test")
        self.assertFalse(self.dialogs.has_open_session("ttnpc:one"))


class DialogParserTests(unittest.TestCase):
    def test_guard_classification_separates_rewards_from_navigation(self) -> None:
        from server.content.worlds import DialogChoice
        from server.services.dialogs import dialog_choice_guarded

        def bare(**overrides):
            values = {
                "index": 0, "label": "X", "action_id": "start:0", "next_node_id": "start",
                "end": False, "when": None, "script": None, "action": None,
                "give_card": None, "start_task": None, "grant": 0,
                "vibe_delta": 0, "grant_bops": 0, "repeatable": False,
            }
            values.update(overrides)
            return DialogChoice(**values)

        self.assertFalse(dialog_choice_guarded(bare()))
        self.assertFalse(dialog_choice_guarded(bare(vibe_delta=2, repeatable=True)))
        self.assertFalse(dialog_choice_guarded(bare(vibe_delta=2)))
        self.assertTrue(dialog_choice_guarded(bare(grant=1)))
        self.assertTrue(dialog_choice_guarded(bare(grant_bops=3)))
        self.assertTrue(dialog_choice_guarded(bare(give_card="card-a")))
        self.assertTrue(dialog_choice_guarded(bare(start_task="task-1")))
        self.assertTrue(dialog_choice_guarded(bare(action="tinytown_claim:x:1:0")))

    def test_new_choice_fields_parse(self) -> None:
        choice = _parse_dialog_choice(
            {"label": "Go", "end": True, "vibe_delta": 2, "grant_bops": 5},
            peep_id="wren",
            node_id="start",
            index=0,
            card_ids={"card-a"},
        )
        self.assertEqual(choice.vibe_delta, 2)
        self.assertEqual(choice.grant_bops, 5)
        self.assertFalse(choice.repeatable)
        chatty = _parse_dialog_choice(
            {"label": "Chat", "next": "start", "repeatable": True},
            peep_id="wren",
            node_id="start",
            index=1,
            card_ids={"card-a"},
        )
        self.assertTrue(chatty.repeatable)

    def test_repeatable_choices_cannot_carry_rewards(self) -> None:
        from server.content.common import ContentError

        for raw in ({"label": "Go", "end": True, "repeatable": True, "grant": 1},
                    {"label": "Go", "end": True, "repeatable": True, "grant_bops": 1},
                    {"label": "Go", "end": True, "repeatable": True, "give_card": "card-a"}):
            with self.assertRaises(ContentError, msg=str(raw)):
                _parse_dialog_choice(raw, peep_id="wren", node_id="start", index=0, card_ids={"card-a"})

    def test_invalid_numbers_rejected(self) -> None:
        from server.content.common import ContentError

        with self.assertRaises(ContentError):
            _parse_dialog_choice(
                {"label": "Go", "end": True, "vibe_delta": "lots"},
                peep_id="wren", node_id="start", index=0, card_ids=set(),
            )


if __name__ == "__main__":
    unittest.main()
