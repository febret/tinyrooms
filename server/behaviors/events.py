"""Typed behavior events passed to trusted world scripts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


BEHAVIOR_EVENT_TYPES = frozenset(
    {"tick", "enter", "leave", "quick_action", "card_play", "dialog_action", "activity_result"}
)
PEEP_KINDS = frozenset({"user", "npc"})


@dataclass(frozen=True, slots=True)
class PeepRef:
    """A reference to a user or NPC peep."""

    kind: str
    peep_id: str | None
    account_id: str | None


@dataclass(frozen=True, slots=True)
class PropRef:
    """A reference to a placed prop instance."""

    instance_id: str
    prop_id: str
    room_id: str


@dataclass(frozen=True, slots=True)
class BehaviorEvent:
    """A single typed behavior event delivered to world scripts."""

    type: str
    actor: PeepRef
    target: PeepRef | PropRef | None = None
    room_id: str | None = None
    action: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)
