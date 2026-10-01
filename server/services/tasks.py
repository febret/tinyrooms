"""Persistent, idempotent task progress and rewards for the Journal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import logging
import sqlite3
from zoneinfo import ZoneInfo

from server.content.gameplay import GameplayContent
from server.content.tasks import TaskDefinition, TaskReward, TaskStep
from server.game_time import game_date, today_in
from server.profiles import ProfileRepository
from server.security import utc_now
from server.services.task_feedback import TaskChange
from server.state.migrations import DatabaseHub


LOGGER = logging.getLogger("tinyrooms.tasks")


@dataclass(frozen=True, slots=True)
class TaskStepView:
    """Per-step progress inside a task view."""

    step_id: str
    title: str
    trigger: str
    amount: int
    progress: int
    memory_tag: str | None

    @property
    def complete(self) -> bool:
        """Return whether the step has reached its target amount."""

        return self.progress >= self.amount

    def to_payload(self) -> dict[str, object]:
        """Serialize the step progress."""

        return {
            "step_id": self.step_id,
            "title": self.title,
            "trigger": self.trigger,
            "amount": self.amount,
            "progress": self.progress,
            "complete": self.complete,
            "memory_tag": self.memory_tag,
        }


@dataclass(frozen=True, slots=True)
class TaskView:
    """A task definition joined with one account's progress."""

    id: str
    scope: str
    title: str
    description: str
    status: str
    revision: int
    steps: tuple[TaskStepView, ...]
    reward: TaskReward
    memory_tags: tuple[str, ...]
    repeatable: bool
    reset_policy: str | None
    started_at: str
    completed_at: str | None

    def to_payload(self) -> dict[str, object]:
        """Serialize the task and its progress for the client."""

        return {
            "id": self.id,
            "scope": self.scope,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "revision": self.revision,
            "steps": [step.to_payload() for step in self.steps],
            "reward": self.reward.to_payload(),
            "memory_tags": list(self.memory_tags),
            "repeatable": self.repeatable,
            "reset_policy": self.reset_policy,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class TaskService:
    """Advances ordered task steps, grants rewards once, and records memories."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: object,
        progression: object,
        content: GameplayContent,
        world_id: str,
        task_definitions: Mapping[str, TaskDefinition],
        timezone: ZoneInfo,
        memories: object | None = None,
        cutscenes: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._progression = progression
        self._content = content
        self._world_id = world_id
        self._definitions = dict(task_definitions)
        self._timezone = timezone
        self._memories = memories
        self._cutscenes = cutscenes

    def _local_date(self, iso_timestamp: str | None) -> str:
        return game_date(iso_timestamp, self._timezone)

    def _today(self) -> str:
        return today_in(self._timezone)

    def _ledger_key(self, definition: TaskDefinition, game_day: str) -> str:
        base = f"task:{definition.id}"
        return f"{base}:{game_day}" if definition.repeatable else base

    def _participant_account_ids(self, definition: TaskDefinition) -> set[str]:
        account_ids: set[str] = set()
        for entry in definition.participants:
            if entry == "room" or entry == "personal":
                continue
            account = self._profiles.resolve_account(entry)
            if account is not None:
                account_ids.add(account.id)
        return account_ids

    def _credit_eligible(self, account_id: str, definition: TaskDefinition) -> bool:
        if definition.scope != "shared" or definition.credit == "actor":
            return True
        if "room" in definition.participants:
            return True
        return account_id in self._participant_account_ids(definition)

    def _reward_recipients(self, definition: TaskDefinition, actor_account_id: str) -> list[str]:
        if definition.reward_recipients != "all_participants":
            return [actor_account_id]
        recipients = self._participant_account_ids(definition)
        recipients.add(actor_account_id)
        return sorted(recipients)

    def _steps_from_definition(self, definition: TaskDefinition) -> list[dict[str, object]]:
        return [{"step_id": step.step_id, "progress": 0} for step in definition.steps]

    def _reconcile_steps(self, definition: TaskDefinition, raw: object) -> list[dict[str, object]]:
        stored: dict[str, int] = {}
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and "step_id" in entry:
                    try:
                        stored[str(entry["step_id"])] = int(entry.get("progress", 0))
                    except (TypeError, ValueError):
                        continue
        steps: list[dict[str, object]] = []
        for step in definition.steps:
            progress = stored.get(step.step_id, 0)
            steps.append({"step_id": step.step_id, "progress": max(0, min(progress, step.amount))})
        return steps

    def _first_incomplete(self, definition: TaskDefinition, steps: list[dict[str, object]]) -> int | None:
        for index, step in enumerate(definition.steps):
            if int(steps[index]["progress"]) < step.amount:
                return index
        return None

    def _all_complete(self, definition: TaskDefinition, steps: list[dict[str, object]]) -> bool:
        return all(int(steps[index]["progress"]) >= step.amount for index, step in enumerate(definition.steps))

    def _reset_due(self, definition: TaskDefinition, completed_at: str | None) -> bool:
        if not definition.repeatable or definition.reset_policy != "daily":
            return False
        return self._local_date(completed_at) < self._today()

    def _load_row(self, connection: sqlite3.Connection, account_id: str, task_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM task_progress WHERE account_id = ? AND task_id = ?",
            (account_id, task_id),
        ).fetchone()

    def _write_row(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
        steps: list[dict[str, object]],
        status: str,
        started_at: str,
        completed_at: str | None,
        reward_operation_id: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO task_progress (
                account_id, task_id, world_id, scope, status, steps_json, started_at,
                completed_at, definition_revision, reward_operation_id, shared_owner_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, task_id) DO UPDATE SET
                scope = excluded.scope,
                status = excluded.status,
                steps_json = excluded.steps_json,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                definition_revision = excluded.definition_revision,
                reward_operation_id = excluded.reward_operation_id,
                shared_owner_id = excluded.shared_owner_id
            """,
            (
                account_id,
                definition.id,
                self._world_id,
                definition.scope,
                status,
                json.dumps(steps),
                started_at,
                completed_at,
                definition.revision,
                reward_operation_id,
                self._world_id if definition.scope == "shared" else None,
            ),
        )

    def _prepare_state(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
        row: sqlite3.Row | None,
    ) -> dict[str, object] | None:
        now = utc_now().isoformat()
        if row is None:
            return {
                "steps": self._steps_from_definition(definition),
                "status": "active",
                "started_at": now,
                "completed_at": None,
                "reward_operation_id": None,
            }
        status = str(row["status"])
        if int(row["definition_revision"]) != definition.revision:
            return {
                "steps": self._steps_from_definition(definition),
                "status": "active",
                "started_at": now,
                "completed_at": None,
                "reward_operation_id": None,
            }
        if status == "completed":
            if not self._reset_due(definition, row["completed_at"]):
                return None
            return {
                "steps": self._steps_from_definition(definition),
                "status": "active",
                "started_at": now,
                "completed_at": None,
                "reward_operation_id": None,
            }
        try:
            raw = json.loads(row["steps_json"])
        except (TypeError, ValueError):
            raw = []
        return {
            "steps": self._reconcile_steps(definition, raw),
            "status": "active",
            "started_at": row["started_at"],
            "completed_at": None,
            "reward_operation_id": row["reward_operation_id"],
        }

    def _record_step_memory(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
        step: TaskStep,
    ) -> str | None:
        if self._memories is None or not step.memory_tag:
            return None
        tags = (step.memory_tag, f"task:{definition.id}")
        text = step.title or step.step_id
        self._memories.create_game_in_transaction(connection, account_id, text, tags, task_id=definition.id)
        return text

    def _record_completion_memory(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
    ) -> str | None:
        if self._memories is None:
            return None
        tags = tuple(definition.memory_tags) + (f"task:{definition.id}",)
        text = f"Completed: {definition.title}"
        self._memories.create_game_in_transaction(
            connection,
            account_id,
            text,
            tags,
            task_id=definition.id,
        )
        return text

    def _complete(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
        state: dict[str, object],
    ) -> str | None:
        now = utc_now().isoformat()
        state["status"] = "completed"
        state["completed_at"] = now
        game_day = self._local_date(now)
        ledger_key = self._ledger_key(definition, game_day)
        for recipient in self._reward_recipients(definition, account_id):
            self._progression.grant_in_transaction(
                connection,
                recipient,
                kudos=definition.reward.kudos,
                cards=definition.reward.cards,
                ledger_key=ledger_key,
                kind="task",
            )
        memory_text = self._record_completion_memory(connection, account_id, definition)
        state["reward_operation_id"] = ledger_key
        return memory_text

    def _advance(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: TaskDefinition,
        state: dict[str, object],
        index: int,
        increment: int,
    ) -> list[TaskChange]:
        steps = state["steps"]
        assert isinstance(steps, list)
        step = definition.steps[index]
        current = int(steps[index]["progress"])
        steps[index]["progress"] = min(step.amount, current + increment)
        memory_texts: list[str] = []
        step_completed = int(steps[index]["progress"]) >= step.amount and current < step.amount
        if step_completed:
            text = self._record_step_memory(connection, account_id, definition, step)
            if text:
                memory_texts.append(text)
        completed = self._all_complete(definition, steps)
        if completed:
            text = self._complete(connection, account_id, definition, state)
            if text:
                memory_texts.append(text)
        self._write_row(
            connection,
            account_id,
            definition,
            steps,
            str(state["status"]),
            str(state["started_at"]),
            state["completed_at"] if isinstance(state["completed_at"], str) else None,
            state["reward_operation_id"] if isinstance(state["reward_operation_id"], str) else None,
        )
        if completed:
            kind = "completed"
        elif step_completed:
            kind = "step_completed"
        else:
            return []
        return [
            TaskChange(
                account_id=account_id,
                task_id=definition.id,
                task_title=definition.title,
                kind=kind,
                step_id=step.step_id,
                step_title=step.title,
                memory_texts=tuple(memory_texts),
            )
        ]

    def _view_from_row(
        self,
        definition: TaskDefinition,
        row: sqlite3.Row | None,
    ) -> TaskView | None:
        if row is None:
            return None
        try:
            raw = json.loads(row["steps_json"])
        except (TypeError, ValueError):
            raw = []
        reconciled = self._reconcile_steps(definition, raw)
        steps = tuple(
            TaskStepView(
                step_id=step.step_id,
                title=step.title,
                trigger=step.trigger,
                amount=step.amount,
                progress=int(reconciled[index]["progress"]),
                memory_tag=step.memory_tag,
            )
            for index, step in enumerate(definition.steps)
        )
        return TaskView(
            id=definition.id,
            scope=definition.scope,
            title=definition.title,
            description=definition.description,
            status=str(row["status"]),
            revision=definition.revision,
            steps=steps,
            reward=definition.reward,
            memory_tags=tuple(definition.memory_tags),
            repeatable=definition.repeatable,
            reset_policy=definition.reset_policy,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def _reset_if_due(self, account_id: str, definition: TaskDefinition, row: sqlite3.Row) -> None:
        if str(row["status"]) != "completed" or not self._reset_due(definition, row["completed_at"]):
            return
        with self._hub.transaction() as connection:
            latest = self._load_row(connection, account_id, definition.id)
            if latest is None:
                return
            state = self._prepare_state(connection, account_id, definition, latest)
            if state is None:
                return
            self._write_row(
                connection,
                account_id,
                definition,
                state["steps"],
                str(state["status"]),
                str(state["started_at"]),
                None,
                None,
            )

    def list_for_account(self, account_id: str) -> list[TaskView]:
        """List every started task for the account, newest definitions included."""

        if self._profiles.get_account_by_id(account_id) is None:
            return []
        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM task_progress WHERE account_id = ? AND world_id = ?",
                (account_id, self._world_id),
            ).fetchall()
        by_task = {row["task_id"]: row for row in rows}
        views: list[TaskView] = []
        for task_id in sorted(self._definitions):
            definition = self._definitions[task_id]
            row = by_task.get(task_id)
            if row is None:
                continue
            if str(row["status"]) == "completed" and self._reset_due(definition, row["completed_at"]):
                self._reset_if_due(account_id, definition, row)
                with self._hub.locked() as connection:
                    row = self._load_row(connection, account_id, task_id)
            view = self._view_from_row(definition, row)
            if view is not None:
                views.append(view)
        return views

    def view_payload(self, account_id: str) -> dict[str, object]:
        """Return active and completed task groups for bootstrap and commands."""

        views = self.list_for_account(account_id)
        return {
            "active": [view.to_payload() for view in views if view.status == "active"],
            "completed": [view.to_payload() for view in views if view.status == "completed"],
        }

    def view(self, account_id: str, task_id: str) -> dict[str, object] | None:
        """Return a single serialized task view, or None when unknown or unstarted."""

        definition = self._definitions.get(task_id)
        if definition is None:
            return None
        with self._hub.locked() as connection:
            row = self._load_row(connection, account_id, task_id)
        view = self._view_from_row(definition, row)
        return None if view is None else view.to_payload()

    def start(self, account_id: str, task_id: str) -> list[TaskChange]:
        """Start a task lazily; starting an already-active task is a no-op."""

        with self._hub.transaction() as connection:
            change = self.start_in_transaction(connection, account_id, task_id)
        return [change] if change is not None else []

    def start_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        task_id: str,
    ) -> TaskChange | None:
        """Start a task inside a caller-owned transaction.

        Returns a ``started`` change when a task row is created or reset, so the
        caller can emit feedback once its transaction has committed.
        """

        definition = self._definitions.get(task_id)
        if definition is None or self._profiles.get_account_by_id(account_id) is None:
            return None
        row = self._load_row(connection, account_id, task_id)
        state = self._prepare_state(connection, account_id, definition, row)
        if state is None:
            return None
        started = row is None or str(row["status"]) != "active"
        if started:
            self._write_row(
                connection,
                account_id,
                definition,
                state["steps"],
                str(state["status"]),
                str(state["started_at"]),
                None,
                None,
            )
        if not started:
            return None
        return TaskChange(
            account_id=account_id,
            task_id=definition.id,
            task_title=definition.title,
            kind="started",
        )

    def record(
        self,
        account_id: str,
        trigger: str,
        fields: Mapping[str, object],
        *,
        source: str | None = None,
    ) -> list[TaskChange]:
        """Advance every active task step matching a behavior event trigger.

        Malformed triggers and unknown accounts are ignored so a bad authored
        event can never raise through a room command.
        """

        del source
        if not trigger or not self._definitions:
            return []
        try:
            return self._record(account_id, trigger, fields)
        except Exception as exc:  # noqa: BLE001 - task triggers must never break rooms
            LOGGER.warning("task.record.failed account_id=%s trigger=%s error=%s", account_id, trigger, exc)
            return []

    def _record(self, account_id: str, trigger: str, fields: Mapping[str, object]) -> list[TaskChange]:
        if self._profiles.get_account_by_id(account_id) is None:
            return []
        changes: list[TaskChange] = []
        with self._hub.transaction() as connection:
            for task_id in sorted(self._definitions):
                definition = self._definitions[task_id]
                if not self._credit_eligible(account_id, definition):
                    continue
                row = self._load_row(connection, account_id, task_id)
                started = row is None or str(row["status"]) != "active"
                state = self._prepare_state(connection, account_id, definition, row)
                if state is None:
                    continue
                steps = state["steps"]
                assert isinstance(steps, list)
                index = self._first_incomplete(definition, steps)
                if index is None:
                    continue
                step = definition.steps[index]
                if step.trigger != trigger or not step.matches(fields):
                    continue
                if started:
                    changes.append(
                        TaskChange(
                            account_id=account_id,
                            task_id=definition.id,
                            task_title=definition.title,
                            kind="started",
                        )
                    )
                changes.extend(self._advance(connection, account_id, definition, state, index, 1))
        return changes

    def advance_step(
        self,
        account_id: str,
        task_id: str,
        step_id: str | None = None,
        amount: int = 1,
    ) -> list[TaskChange]:
        """Advance an explicit task step for a behavior intent, enforcing order."""

        definition = self._definitions.get(task_id)
        if definition is None or self._profiles.get_account_by_id(account_id) is None:
            return []
        increment = max(1, int(amount))
        with self._hub.transaction() as connection:
            row = self._load_row(connection, account_id, task_id)
            state = self._prepare_state(connection, account_id, definition, row)
            if state is None:
                return []
            steps = state["steps"]
            assert isinstance(steps, list)
            if step_id is not None:
                index = next((i for i, step in enumerate(definition.steps) if step.step_id == step_id), None)
                if index is None:
                    return []
                if any(int(steps[i]["progress"]) < definition.steps[i].amount for i in range(index)):
                    return []
            else:
                index = self._first_incomplete(definition, steps)
                if index is None:
                    return []
            return self._advance(connection, account_id, definition, state, index, increment)

    def feedback_events(
        self,
        account_id: str,
        changes: list[TaskChange],
        *,
        room_id: str = "",
    ) -> list[dict[str, object]]:
        """Build client events for task changes after a committed transaction.

        Emits a private ``cutscene.play`` for each started/completed change and a
        ``toast`` for every memory the change wrote. A missing cutscene service
        or definition degrades to toasts only.
        """

        if not changes:
            return []
        events: list[dict[str, object]] = []
        account = self._profiles.get_account_by_id(account_id)
        for change in changes:
            if self._cutscenes is not None and account is not None:
                reference = "task-started" if change.kind == "started" else "task-completed"
                try:
                    definition = self._cutscenes.resolve(reference)
                    launch = self._cutscenes.launch(
                        definition=definition,
                        account=account,
                        room_id=room_id,
                        audience="private",
                        origin="journal",
                        params={
                            "task_id": change.task_id,
                            "task_title": change.task_title,
                            "step_title": change.step_title or "",
                            "task_complete": change.kind == "completed",
                        },
                    )
                    events.append(launch.event)
                except Exception as exc:  # noqa: BLE001 - feedback must never break the caller
                    LOGGER.warning("task.feedback.failed task_id=%s error=%s", change.task_id, exc)
            for text in change.memory_texts:
                events.append({"type": "toast", "tone": "success", "text": f"Memory added: {text}"})
        return events
