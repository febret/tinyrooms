"""Effective peep-state calculation combining all modifier sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from server.content.gameplay import GameplayContent
from server.game.modifiers import (
    MAX_CLEANLINESS_TARGET,
    MAX_ENERGY_TARGET,
    MAX_HEALTH_TARGET,
    STAT_TARGETS,
    Modifier,
    effective_value,
    modifiers_for,
)

BASE_HEALTH = 50
BASE_CLEANLINESS = 100


@dataclass(frozen=True, slots=True)
class EffectivePeepState:
    """The canonical state every UI and action validation must agree on."""

    stats: dict[str, int]
    max_health: int
    max_energy: int
    max_cleanliness: int
    statuses: tuple[str, ...]

    def stat(self, target: str) -> int:
        """Return an effective stat, defaulting to zero when unknown."""

        return self.stats.get(target, 0)


def status_modifiers(content: GameplayContent, active_statuses: Sequence[str]) -> tuple[Modifier, ...]:
    """Return flat stat modifiers contributed by active statuses."""

    result: list[Modifier] = []
    for status_id in active_statuses:
        definition = content.statuses.get(status_id)
        if definition is None:
            continue
        for stat_id, delta in definition.stat_effects.items():
            result.append(Modifier(target=stat_id, flat=float(delta)))
    return tuple(result)


def reconcile_statuses(
    content: GameplayContent,
    *,
    previous: Sequence[str],
    counters: Mapping[str, float],
    maxima: Mapping[str, float],
) -> tuple[str, ...]:
    """Apply/clear statuses using their conditions with hysteresis.

    A status already active only clears when its clear condition matches; a new
    status applies only when its apply condition matches. Each status occurs at
    most once per peep.
    """

    active = list(dict.fromkeys(previous))
    for status_id, definition in content.statuses.items():
        value = float(counters.get(definition.applied_when.counter, 0.0))
        maximum = float(maxima.get(definition.applied_when.counter, 0.0))
        if status_id in active:
            clear_value = float(counters.get(definition.cleared_when.counter, 0.0))
            clear_maximum = float(maxima.get(definition.cleared_when.counter, 0.0))
            if definition.cleared_when.matches(clear_value, clear_maximum):
                active.remove(status_id)
        else:
            if definition.applied_when.matches(value, maximum):
                active.append(status_id)
    return tuple(active)


def _base_maxima(
    content: GameplayContent,
    level: int,
    modifiers: Sequence[Modifier],
) -> tuple[int, int, int]:
    """Return (max_health, max_energy, max_cleanliness)."""

    constitution = effective_value(1, modifiers_for(modifiers, "constitution"), minimum=0)
    max_health_base = max(BASE_HEALTH, BASE_HEALTH * constitution)
    max_health = effective_value(max_health_base, modifiers_for(modifiers, MAX_HEALTH_TARGET), minimum=1)
    max_energy = effective_value(
        content.juice.max_energy(level),
        modifiers_for(modifiers, MAX_ENERGY_TARGET),
        minimum=1,
    )
    max_cleanliness = effective_value(
        BASE_CLEANLINESS,
        modifiers_for(modifiers, MAX_CLEANLINESS_TARGET),
        minimum=1,
    )
    return max_health, max_energy, max_cleanliness


def compute_effective_state(
    content: GameplayContent,
    *,
    level: int,
    counters: Mapping[str, float],
    previous_statuses: Sequence[str] = (),
    modifiers: Sequence[Modifier] = (),
) -> EffectivePeepState:
    """Compute the full effective state given counters, equipment/skills/buffs.

    Statuses are reconciled first using non-status modifiers, then status stat
    effects feed back into the final calculation so every caller sees identical
    results.
    """

    pass_one = _base_maxima(content, level, modifiers)
    maxima = {
        "health": pass_one[0],
        "energy": pass_one[1],
        "cleanliness": pass_one[2],
    }
    statuses = reconcile_statuses(
        content,
        previous=previous_statuses,
        counters=counters,
        maxima=maxima,
    )
    all_modifiers = (*modifiers, *status_modifiers(content, statuses))
    stats = {
        stat: effective_value(1, modifiers_for(all_modifiers, stat), minimum=0) for stat in STAT_TARGETS
    }
    max_health, max_energy, max_cleanliness = _base_maxima(content, level, all_modifiers)
    return EffectivePeepState(
        stats=stats,
        max_health=max_health,
        max_energy=max_energy,
        max_cleanliness=max_cleanliness,
        statuses=statuses,
    )
