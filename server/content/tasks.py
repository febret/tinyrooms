"""Strict task definition loader for world content."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping


TASK_TRIGGERS = frozenset(
    {"go", "card_play", "dialog_action", "activity_result", "prop_action", "enter_room"}
)
TASK_SCOPES = frozenset({"personal", "shared"})
TASK_CREDIT_POLICIES = frozenset({"actor", "participants"})
TASK_REWARD_RECIPIENTS = frozenset({"actor", "all_participants"})
TASK_RESET_POLICIES = frozenset({"daily"})


@dataclass(frozen=True, slots=True)
class TaskStep:
    """One ordered objective inside a task definition."""

    step_id: str
    trigger: str
    amount: int = 1
    title: str = ""
    memory_tag: str | None = None
    match: Mapping[str, str] = field(default_factory=dict)

    def matches(self, fields: Mapping[str, object]) -> bool:
        """Return whether the supplied event fields satisfy every requirement."""

        for key, expected in self.match.items():
            if str(fields.get(key, "")) != expected:
                return False
        return True

    def to_payload(self) -> dict[str, object]:
        """Serialize the immutable step definition."""

        return {
            "step_id": self.step_id,
            "trigger": self.trigger,
            "amount": self.amount,
            "title": self.title,
            "memory_tag": self.memory_tag,
            "match": dict(self.match),
        }


@dataclass(frozen=True, slots=True)
class TaskReward:
    """The one-time reward granted when a task completes."""

    kudos: int = 0
    cards: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        """Serialize the reward definition."""

        return {"kudos": self.kudos, "cards": list(self.cards)}


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    """A validated, immutable task definition."""

    id: str
    scope: str
    title: str
    description: str
    steps: tuple[TaskStep, ...]
    reward: TaskReward
    memory_tags: tuple[str, ...]
    repeatable: bool = False
    reset_policy: str | None = None
    participants: tuple[str, ...] = ("personal",)
    credit: str = "actor"
    reward_recipients: str = "actor"
    revision: int = 1

    def to_payload(self) -> dict[str, object]:
        """Serialize the definition without runtime progress."""

        return {
            "id": self.id,
            "scope": self.scope,
            "title": self.title,
            "description": self.description,
            "steps": [step.to_payload() for step in self.steps],
            "reward": self.reward.to_payload(),
            "memory_tags": list(self.memory_tags),
            "repeatable": self.repeatable,
            "reset_policy": self.reset_policy,
            "participants": list(self.participants),
            "credit": self.credit,
            "reward_recipients": self.reward_recipients,
            "revision": self.revision,
        }


def _parse_match(raw_value: Any, task_id: str, step_id: str, path: Path) -> dict[str, str]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ContentError(f"Task '{task_id}' step '{step_id}' match must be a mapping in {path}.")
    match: dict[str, str] = {}
    for key, value in raw_value.items():
        if not isinstance(key, str) or not key:
            raise ContentError(f"Task '{task_id}' step '{step_id}' has an invalid match key.")
        match[key] = str(value)
    return match


def _parse_step(raw_step: Any, task_id: str, index: int, path: Path) -> TaskStep:
    if not isinstance(raw_step, dict):
        raise ContentError(f"Task '{task_id}' step {index} must be a mapping in {path}.")
    step_id = str(raw_step.get("step_id", "")).strip()
    if not step_id:
        raise ContentError(f"Task '{task_id}' step {index} must define step_id.")
    trigger = str(raw_step.get("trigger", "")).strip()
    if trigger not in TASK_TRIGGERS:
        raise ContentError(
            f"Task '{task_id}' step '{step_id}' has unknown trigger '{trigger}'. "
            f"Expected one of {', '.join(sorted(TASK_TRIGGERS))}."
        )
    raw_amount = raw_step.get("amount", 1)
    if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount < 1:
        raise ContentError(f"Task '{task_id}' step '{step_id}' has an invalid amount {raw_amount!r}.")
    memory_tag = raw_step.get("memory_tag")
    return TaskStep(
        step_id=step_id,
        trigger=trigger,
        amount=int(raw_amount),
        title=str(raw_step.get("title", "")).strip(),
        memory_tag=str(memory_tag).strip() if memory_tag is not None else None,
        match=_parse_match(raw_step.get("match"), task_id, step_id, path),
    )


def _parse_reward(raw_reward: Any, task_id: str, card_ids: set[str], path: Path) -> TaskReward:
    if raw_reward is None:
        return TaskReward()
    if not isinstance(raw_reward, dict):
        raise ContentError(f"Task '{task_id}' reward must be a mapping in {path}.")
    raw_kudos = raw_reward.get("kudos", 0)
    if isinstance(raw_kudos, bool) or not isinstance(raw_kudos, int) or raw_kudos < 0:
        raise ContentError(f"Task '{task_id}' has an invalid reward kudos {raw_kudos!r}.")
    raw_cards = raw_reward.get("cards", []) or []
    if not isinstance(raw_cards, list):
        raise ContentError(f"Task '{task_id}' reward cards must be a list.")
    cards = tuple(str(card_id) for card_id in raw_cards)
    for card_id in cards:
        if card_id not in card_ids:
            raise ContentError(f"Task '{task_id}' reward references unknown card '{card_id}'.")
    return TaskReward(kudos=int(raw_kudos), cards=cards)


def _parse_definition(task_id: str, raw: Any, card_ids: set[str], path: Path) -> TaskDefinition:
    if not isinstance(raw, dict):
        raise ContentError(f"Task '{task_id}' must be a mapping in {path}.")
    title = str(raw.get("title", "")).strip()
    if not title:
        raise ContentError(f"Task '{task_id}' must define a title.")
    scope = str(raw.get("scope", "personal")).strip() or "personal"
    if scope not in TASK_SCOPES:
        raise ContentError(f"Task '{task_id}' has unknown scope '{scope}'.")
    raw_revision = raw.get("revision", 1)
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 1:
        raise ContentError(f"Task '{task_id}' has an invalid revision {raw_revision!r}.")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ContentError(f"Task '{task_id}' must define a non-empty steps list.")
    steps = tuple(_parse_step(raw_step, task_id, index, path) for index, raw_step in enumerate(raw_steps))
    step_ids = [step.step_id for step in steps]
    if len(set(step_ids)) != len(step_ids):
        raise ContentError(f"Task '{task_id}' has duplicate step ids.")
    raw_tags = raw.get("memory_tags", []) or []
    if not isinstance(raw_tags, list):
        raise ContentError(f"Task '{task_id}' memory_tags must be a list.")
    memory_tags = tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
    repeatable = bool(raw.get("repeatable", False))
    raw_reset = raw.get("reset_policy")
    reset_policy = str(raw_reset).strip() if raw_reset is not None else None
    if repeatable:
        if reset_policy not in TASK_RESET_POLICIES:
            raise ContentError(
                f"Repeatable task '{task_id}' must define reset_policy in "
                f"{', '.join(sorted(TASK_RESET_POLICIES))}."
            )
    elif reset_policy is not None:
        raise ContentError(f"Task '{task_id}' defines reset_policy but is not repeatable.")
    raw_participants = raw.get("participants")
    if raw_participants is None:
        participants = ("personal",)
    elif isinstance(raw_participants, list):
        participants = tuple(str(entry).strip() for entry in raw_participants if str(entry).strip())
    else:
        raise ContentError(f"Task '{task_id}' participants must be a list.")
    if scope == "shared" and not participants:
        raise ContentError(f"Shared task '{task_id}' must define participants.")
    credit = str(raw.get("credit", "actor")).strip() or "actor"
    if credit not in TASK_CREDIT_POLICIES:
        raise ContentError(f"Task '{task_id}' has unknown credit policy '{credit}'.")
    reward_recipients = str(raw.get("reward_recipients", "actor")).strip() or "actor"
    if reward_recipients not in TASK_REWARD_RECIPIENTS:
        raise ContentError(f"Task '{task_id}' has unknown reward_recipients '{reward_recipients}'.")
    return TaskDefinition(
        id=task_id,
        scope=scope,
        title=title,
        description=str(raw.get("description", "")).strip(),
        steps=steps,
        reward=_parse_reward(raw.get("reward"), task_id, card_ids, path),
        memory_tags=memory_tags,
        repeatable=repeatable,
        reset_policy=reset_policy,
        participants=participants,
        credit=credit,
        reward_recipients=reward_recipients,
        revision=int(raw_revision),
    )


def load_task_definitions(world_path: Path, card_ids: set[str]) -> dict[str, TaskDefinition]:
    """Load and validate every task definition for a world."""

    path = world_path / "tasks.yaml"
    if not path.is_file():
        return {}
    payload = require_mapping(load_yaml_file(path), path)
    tasks: dict[str, TaskDefinition] = {}
    for task_id, raw in payload.items():
        if not isinstance(task_id, str) or not task_id:
            raise ContentError(f"{path} contains an invalid task entry.")
        tasks[task_id] = _parse_definition(task_id, raw, card_ids, path)
    return tasks
