"""Timed, daily, and explicitly stackable buff instances (pure logic)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from server.game.modifiers import Modifier

TIMED = "timed"
DAILY = "daily"


@dataclass(frozen=True, slots=True)
class BuffInstance:
    """A single applied buff stack with its own expiration."""

    id: str
    label: str
    kind: str
    expires_at: datetime
    modifiers: tuple[Modifier, ...] = ()
    icon: str = ""
    stackable: bool = False
    max_stacks: int = 1

    def to_payload(self) -> dict[str, object]:
        """Serialize the buff instance for persistence."""

        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "expires_at": self.expires_at.isoformat(),
            "icon": self.icon,
            "stackable": self.stackable,
            "max_stacks": self.max_stacks,
            "modifiers": [
                {"target": modifier.target, "flat": modifier.flat, "percent": modifier.percent}
                for modifier in self.modifiers
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> BuffInstance:
        """Rebuild a buff instance from persisted data."""

        raw_modifiers = payload.get("modifiers", []) or []
        modifiers = tuple(
            Modifier(
                target=str(entry.get("target")),
                flat=float(entry.get("flat", 0.0)),
                percent=float(entry.get("percent", 0.0)),
            )
            for entry in raw_modifiers
            if isinstance(entry, dict) and entry.get("target")
        )
        return cls(
            id=str(payload.get("id", "")),
            label=str(payload.get("label", "")),
            kind=str(payload.get("kind", TIMED)),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            modifiers=modifiers,
            icon=str(payload.get("icon", "")),
            stackable=bool(payload.get("stackable", False)),
            max_stacks=int(payload.get("max_stacks", 1) or 1),
        )


def expire(instances: Sequence[BuffInstance], now: datetime) -> list[BuffInstance]:
    """Return the instances that have not yet expired."""

    return [instance for instance in instances if instance.expires_at > now]


def apply_buff(
    instances: Sequence[BuffInstance],
    incoming: BuffInstance,
    now: datetime,
) -> list[BuffInstance]:
    """Apply a buff following refresh/stack/expiration rules."""

    active = expire(instances, now)
    if not incoming.stackable:
        kept = [instance for instance in active if instance.id != incoming.id]
        return [*kept, incoming]
    same_id = [instance for instance in active if instance.id == incoming.id]
    others = [instance for instance in active if instance.id != incoming.id]
    limit = max(1, incoming.max_stacks)
    if len(same_id) >= limit:
        same_id = sorted(same_id, key=lambda instance: instance.expires_at)[1:]
    return [*others, *same_id, incoming]


def active_modifiers(instances: Sequence[BuffInstance], now: datetime) -> tuple[Modifier, ...]:
    """Return the modifiers from all non-expired buff instances."""

    modifiers: list[Modifier] = []
    for instance in expire(instances, now):
        modifiers.extend(instance.modifiers)
    return tuple(modifiers)
