"""Milestone 3 Phase B task persistence and reward tests."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef
from server.behaviors.loader import BehaviorAttachment, BehaviorScript, BehaviorScripts
from server.content.common import ContentError
from server.content.tasks import TaskDefinition, TaskReward, TaskStep, load_task_definitions
from server.services.activities import ActivityService
from server.services.dialogs import DialogService
from server.services.memories import MemoryService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from server.services.tasks import TaskService
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world
from tests.test_milestone1 import RuntimeTestCase, websocket_headers


UTC = ZoneInfo("UTC")


def make_step(step_id, trigger, *, amount=1, match=None, title="", memory_tag=None):
    """Build a task step for tests."""

    return TaskStep(
        step_id=step_id,
        trigger=trigger,
        amount=amount,
        title=title or step_id,
        memory_tag=memory_tag,
        match=match or {},
    )


def make_task(
    task_id,
    steps,
    *,
    scope="personal",
    credit="actor",
    reward_recipients="actor",
    participants=("personal",),
    repeatable=False,
    reset_policy=None,
    kudos=0,
    cards=(),
    memory_tags=(),
    revision=1,
):
    """Build a task definition for tests."""

    return TaskDefinition(
        id=task_id,
        scope=scope,
        title=task_id.replace("-", " ").title(),
        description="Test task.",
        steps=tuple(steps),
        reward=TaskReward(kudos=kudos, cards=tuple(cards)),
        memory_tags=tuple(memory_tags),
        repeatable=repeatable,
        reset_policy=reset_policy,
        participants=tuple(participants),
        credit=credit,
        reward_recipients=reward_recipients,
        revision=revision,
    )


class TaskServiceTestCase(ServiceTestCase):
    """Shared fixtures for task service tests."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID)
        self.memories = MemoryService(self.hub, self.profiles, WORLD_ID, UTC)

    def build(self, definitions, *, memories=None, timezone=UTC):
        """Construct a TaskService around custom definitions."""

        return TaskService(
            self.hub,
            self.profiles,
            self.stats,
            self.progression,
            self.content,
            WORLD_ID,
            definitions,
            timezone,
            memories=self.memories if memories is None else memories,
        )

    def ledger_count(self, account_id, task_id):
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM reward_ledger WHERE account_id = ? AND ledger_key LIKE ?",
                (account_id, f"task:{task_id}%"),
            ).fetchone()
        return int(row[0])


class PersonalAndSharedCreditTests(TaskServiceTestCase):
    """Credit is personal by default and follows shared policy when authored."""

    def test_personal_progress_belongs_only_to_the_actor(self) -> None:
        actor = self.create_account("actor")
        other = self.create_account("other")
        tasks = self.build({"gather": make_task("gather", [make_step("one", "enter_room", amount=2, match={"room_id": "foyer"})])})
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        actor_view = tasks.view(actor.id, "gather")
        self.assertEqual(actor_view["steps"][0]["progress"], 1)
        self.assertEqual(tasks.list_for_account(other.id), [])

class OrderedProgressTests(TaskServiceTestCase):
    """Later steps never advance before earlier steps complete."""

    def test_out_of_order_triggers_do_not_advance(self) -> None:
        actor = self.create_account("actor")
        tasks = self.build(
            {
                "tour": make_task(
                    "tour",
                    [
                        make_step("enter", "enter_room", match={"room_id": "foyer"}),
                        make_step("talk", "dialog_action", match={"peep_id": "caretaker"}),
                    ],
                )
            }
        )
        tasks.record(actor.id, "dialog_action", {"peep_id": "caretaker"})
        self.assertEqual(tasks.list_for_account(actor.id), [])
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        view = tasks.view(actor.id, "tour")
        self.assertEqual(view["steps"][0]["progress"], 1)
        self.assertEqual(view["steps"][1]["progress"], 0)
        tasks.record(actor.id, "dialog_action", {"peep_id": "caretaker"})
        self.assertEqual(tasks.view(actor.id, "tour")["status"], "completed")


class RewardIdempotencyTests(TaskServiceTestCase):
    """One-time rewards apply exactly once across duplicates and restarts."""

    def test_reward_applies_once_across_duplicates(self) -> None:
        actor = self.create_account("actor")
        tasks = self.build({"gift": make_task("gift", [make_step("one", "enter_room", match={"room_id": "foyer"})], kudos=3)})
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        self.assertEqual(self.reload_account(actor).kudos, 3)
        self.assertEqual(self.ledger_count(actor.id, "gift"), 1)

class RepeatPolicyTests(TaskServiceTestCase):
    """Only explicitly repeatable tasks reset, and only per their policy."""

    def test_daily_task_resets_after_the_game_day(self) -> None:
        actor = self.create_account("actor")
        tasks = self.build(
            {
                "daily": make_task(
                    "daily",
                    [make_step("one", "enter_room", match={"room_id": "foyer"})],
                    repeatable=True,
                    reset_policy="daily",
                    kudos=1,
                )
            }
        )
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        self.assertEqual(self.reload_account(actor).kudos, 1)
        with self.hub.transaction() as connection:
            connection.execute(
                "UPDATE task_progress SET completed_at = '2000-01-01T00:00:00+00:00', "
                "reward_operation_id = 'task:daily:2000-01-01' WHERE account_id = ? AND task_id = 'daily'",
                (actor.id,),
            )
            connection.execute(
                "UPDATE reward_ledger SET ledger_key = 'task:daily:2000-01-01' WHERE account_id = ? AND ledger_key LIKE 'task:daily%'",
                (actor.id,),
            )
        views = tasks.list_for_account(actor.id)
        self.assertEqual(views[0].status, "active")
        tasks.record(actor.id, "enter_room", {"room_id": "foyer"})
        self.assertEqual(self.reload_account(actor).kudos, 2)
        self.assertEqual(self.ledger_count(actor.id, "daily"), 2)

class SharedRewardTests(TaskServiceTestCase):
    """Reward recipients follow the shared-task definition."""

    def test_all_participants_are_rewarded_once(self) -> None:
        actor = self.create_account("actor")
        partner = self.create_account("partner")
        tasks = self.build(
            {
                "coop": make_task(
                    "coop",
                    [make_step("one", "enter_room", match={"room_id": "garden"})],
                    scope="shared",
                    credit="participants",
                    reward_recipients="all_participants",
                    participants=("actor", "partner"),
                    kudos=4,
                )
            }
        )
        tasks.record(actor.id, "enter_room", {"room_id": "garden"})
        self.assertEqual(self.reload_account(actor).kudos, 4)
        self.assertEqual(self.reload_account(partner).kudos, 4)
        tasks.record(actor.id, "enter_room", {"room_id": "garden"})
        self.assertEqual(self.reload_account(partner).kudos, 4)


class DispatcherTaskIntentTests(TaskServiceTestCase, unittest.IsolatedAsyncioTestCase):
    """Behavior intents start tasks and advance explicit steps."""

    def _build_dispatcher(self, tasks, scripts):
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        dialogs = DialogService(
            hub=self.hub,
            profiles=self.profiles,
            stats=self.stats,
            catalog=self.catalog,
            progression=self.progression,
            world=world,
        )
        return BehaviorDispatcher(
            hub=self.hub,
            profiles=self.profiles,
            stats=self.stats,
            progression=self.progression,
            activities=ActivityService(SimpleNamespace(features=frozenset())),
            catalog=self.catalog,
            dialogs=dialogs,
            connections=SimpleNamespace(set_room=lambda *a, **k: None),
            scripts=scripts,
            world=world,
            tasks=tasks,
        )

    async def test_start_and_update_task_intents(self) -> None:
        actor = self.create_account("actor")
        tasks = self.build({"gather": make_task("gather", [make_step("one", "card_play", amount=2, match={"card_id": "poop"})])})

        def handler(context, event):
            context.start_task("gather")
            context.update_task_progress("gather", "one", 1)

        module = ModuleType("task_script")
        module.on_quick_action = handler
        scripts = BehaviorScripts(
            scripts={"task_script": BehaviorScript(script_id="task_script", path=None, module=module)},
            peep_attachments={"molly": BehaviorAttachment("task_script", "peep", "molly", PeepRef("npc", "molly", None))},
            prop_attachments={},
            room_attachments={},
        )
        dispatcher = self._build_dispatcher(tasks, scripts)
        await dispatcher.dispatch(
            BehaviorEvent(
                type="quick_action",
                actor=PeepRef("user", None, actor.id),
                target=PeepRef("npc", "molly", None),
                room_id="playroom",
                action="pet",
            )
        )
        view = tasks.view(actor.id, "gather")
        self.assertEqual(view["steps"][0]["progress"], 1)
        self.assertEqual(view["status"], "active")


class TaskDefinitionLoaderTests(ServiceTestCase):
    """The strict loader validates authored task content."""

    def test_tutorial_tasks_load(self) -> None:
        tasks = load_task_definitions(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.assertIn("house-tour", tasks)
        self.assertEqual(len(tasks["house-tour"].steps), 4)
        self.assertEqual(tasks["house-tour"].reward.kudos, 2)

    def _write(self, text: str):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        (path / "tasks.yaml").write_text(text, encoding="utf-8")
        return path

    def test_duplicate_step_ids_are_rejected(self) -> None:
        path = self._write(
            "t:\n  title: T\n  steps:\n    - {step_id: a, trigger: go}\n    - {step_id: a, trigger: go}\n"
        )
        with self.assertRaises(ContentError):
            load_task_definitions(path, set(self.catalog.cards))

class TaskCommandIntegrationTests(RuntimeTestCase):
    """Bootstrap and websocket commands expose tasks and memories end to end."""

    def test_bootstrap_includes_journal_and_task_progress_records(self) -> None:
        credentials = self.create_ready_account("tourist")
        bootstrap = self.client.get("/api/bootstrap").json()["user"]
        self.assertIn("tasks", bootstrap)
        self.assertEqual(bootstrap["tasks"]["active"], [])
        self.assertIn("journal", bootstrap)
        self.assertIn("summary", bootstrap["journal"])
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.command(socket, "go-1", ".go @way:exit0")["ok"])
            socket.receive_json()
            self.assertTrue(self.command(socket, "go-2", ".go @way:exit0")["ok"])
            socket.receive_json()
            tasks_result = self.command(socket, "tasks-1", ".tasks")
            self.assertTrue(tasks_result["ok"], tasks_result)
            active = tasks_result["payload"]["tasks"]["active"]
            self.assertTrue(any(task["id"] == "house-tour" for task in active), active)
            memory = self.command(socket, "mem-1", ".memory_new First steps")
            self.assertTrue(memory["ok"], memory)
            self.assertTrue(any(entry["text"] == "First steps" for entry in memory["payload"]["journal"]["memories"]))
            listed = self.command(socket, "mem-2", ".memories")
            self.assertTrue(listed["ok"], listed)
            self.assertTrue(any(entry["source_type"] == "manual" for entry in listed["payload"]["journal"]["memories"]))


if __name__ == "__main__":
    unittest.main()
