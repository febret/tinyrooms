"""Modifier combination rules shared by stats, counters, buffs, and equipment."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math

STAT_TARGETS = ("constitution", "dexterity", "charisma", "fanciness")
MAX_HEALTH_TARGET = "max_health"
MAX_ENERGY_TARGET = "max_energy"
MAX_CLEANLINESS_TARGET = "max_cleanliness"
COUNTER_MAX_TARGETS = (MAX_HEALTH_TARGET, MAX_ENERGY_TARGET, MAX_CLEANLINESS_TARGET)
MODIFIER_TARGETS = (*STAT_TARGETS, *COUNTER_MAX_TARGETS)


@dataclass(frozen=True, slots=True)
class Modifier:
    """A flat and/or percentage change to a single stat or counter maximum."""

    target: str
    flat: float = 0.0
    percent: float = 0.0

    def __post_init__(self) -> None:
        if self.target not in MODIFIER_TARGETS:
            raise ValueError(f"Unknown modifier target '{self.target}'.")


def combine(base: float, modifiers: Iterable[Modifier]) -> float:
    """Combine modifiers: add flat changes, then apply summed percentages once."""

    flat = 0.0
    percent = 0.0
    for modifier in modifiers:
        flat += modifier.flat
        percent += modifier.percent
    return (base + flat) * (1.0 + percent)


def effective_value(base: float, modifiers: Sequence[Modifier], *, minimum: int = 0) -> int:
    """Return a floored, bounded whole-number effective value."""

    return max(minimum, math.floor(combine(base, modifiers)))


def modifiers_for(modifiers: Sequence[Modifier], target: str) -> tuple[Modifier, ...]:
    """Return only the modifiers affecting a single target."""

    return tuple(modifier for modifier in modifiers if modifier.target == target)


def clamp_counter(value: float, maximum: float) -> float:
    """Clamp a current counter value to [0, maximum], retaining fractions."""

    return max(0.0, min(float(value), float(maximum)))


def bonuses_to_modifiers(bonuses: dict[str, int], *, multiplier: int = 1) -> tuple[Modifier, ...]:
    """Convert a {target: delta} bonuses mapping into flat modifiers."""

    result: list[Modifier] = []
    for target, delta in bonuses.items():
        if target not in MODIFIER_TARGETS:
            continue
        result.append(Modifier(target=target, flat=float(delta) * multiplier))
    return tuple(result)
