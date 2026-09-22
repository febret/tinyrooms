"""Strict loaders for core gameplay settings and status definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping
from server.game.modifiers import STAT_TARGETS


@dataclass(frozen=True, slots=True)
class StatDefinition:
    """A named base statistic."""

    id: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class StatusCondition:
    """A single counter predicate that applies or clears a status."""

    counter: str
    at_or_below: float | None = None
    at_or_above_fraction: float | None = None
    above: float | None = None

    def matches(self, value: float, maximum: float | None = None) -> bool:
        """Return whether *value* satisfies this condition."""

        if self.at_or_below is not None and value <= self.at_or_below:
            return True
        if self.above is not None and value > self.above:
            return True
        if self.at_or_above_fraction is not None and maximum is not None:
            return value >= maximum * self.at_or_above_fraction
        return False


@dataclass(frozen=True, slots=True)
class StatusDefinition:
    """An automatic counter-driven status such as Sick or Tired."""

    id: str
    label: str
    description: str
    icon: str
    applied_when: StatusCondition
    cleared_when: StatusCondition
    stat_effects: dict[str, float]


@dataclass(frozen=True, slots=True)
class JuiceSettings:
    """Energy recovery and maximum settings."""

    energy_recharge_rate: float
    recovery_threshold: float
    max_energy_per_level: tuple[int, ...]

    def max_energy(self, level: int) -> int:
        """Return the base maximum Energy for a level, clamped to the table."""

        index = max(0, min(int(level), len(self.max_energy_per_level) - 1))
        return self.max_energy_per_level[index]


@dataclass(frozen=True, slots=True)
class LevelDefinition:
    """A single level row with Kudos cost and equipped-stack cap."""

    level: int
    label: str
    kudos_to_next: int | None
    max_equipped: int


@dataclass(frozen=True, slots=True)
class LevelTable:
    """All level definitions keyed by level number."""

    levels: dict[int, LevelDefinition]
    max_level: int

    def get(self, level: int) -> LevelDefinition:
        """Return the definition for *level*, clamped into range."""

        clamped = max(0, min(int(level), self.max_level))
        return self.levels[clamped]

    def equipped_cap(self, level: int) -> int:
        """Return the equipped-stack cap for a level."""

        return self.get(level).max_equipped

    def kudos_to_next(self, level: int) -> int | None:
        """Return Kudos required to leave *level*, or None at the cap."""

        return self.get(level).kudos_to_next


@dataclass(frozen=True, slots=True)
class BopsSettings:
    """Bops economy settings."""

    daily_bops_per_level: tuple[int, ...]
    sticker_swap_cost: int

    def daily_bops(self, level: int) -> int:
        """Return the daily Bops allowance at claim time for a level."""

        index = max(0, min(int(level), len(self.daily_bops_per_level) - 1))
        return self.daily_bops_per_level[index]


@dataclass(frozen=True, slots=True)
class GameplayContent:
    """All loaded core gameplay definitions."""

    stats: dict[str, StatDefinition]
    statuses: dict[str, StatusDefinition]
    juice: JuiceSettings
    levels: LevelTable
    bops: BopsSettings


def _load_stats(path: Path) -> dict[str, StatDefinition]:
    payload = require_mapping(load_yaml_file(path), path)
    stats: dict[str, StatDefinition] = {}
    for stat_id, raw in payload.items():
        if not isinstance(stat_id, str) or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid stat entry.")
        label = str(raw.get("label", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not label or not description:
            raise ContentError(f"Stat '{stat_id}' must define label and description.")
        stats[stat_id] = StatDefinition(id=stat_id, label=label, description=description)
    missing = [stat for stat in STAT_TARGETS if stat not in stats]
    if missing:
        raise ContentError(f"{path} is missing required stats {missing}.")
    return stats


def _parse_condition(raw: Any, status_id: str, path: Path) -> StatusCondition:
    if not isinstance(raw, dict):
        raise ContentError(f"Status '{status_id}' condition must be a mapping in {path}.")
    counter = str(raw.get("counter", "")).strip()
    if not counter:
        raise ContentError(f"Status '{status_id}' condition is missing a counter.")
    at_or_below = raw.get("at_or_below")
    above = raw.get("above")
    at_or_above_fraction = raw.get("at_or_above_fraction")
    provided = [value for value in (at_or_below, above, at_or_above_fraction) if value is not None]
    if len(provided) != 1:
        raise ContentError(f"Status '{status_id}' condition must define exactly one comparison.")
    return StatusCondition(
        counter=counter,
        at_or_below=float(at_or_below) if at_or_below is not None else None,
        at_or_above_fraction=(
            float(at_or_above_fraction) if at_or_above_fraction is not None else None
        ),
        above=float(above) if above is not None else None,
    )


def _load_statuses(path: Path) -> dict[str, StatusDefinition]:
    payload = require_mapping(load_yaml_file(path), path)
    statuses: dict[str, StatusDefinition] = {}
    for status_id, raw in payload.items():
        if not isinstance(status_id, str) or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid status entry.")
        label = str(raw.get("label", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not label or not description:
            raise ContentError(f"Status '{status_id}' must define label and description.")
        effects_raw = raw.get("effects", {}) or {}
        if not isinstance(effects_raw, dict):
            raise ContentError(f"Status '{status_id}' effects must be a mapping.")
        stats_raw = effects_raw.get("stats", {}) or {}
        if not isinstance(stats_raw, dict):
            raise ContentError(f"Status '{status_id}' effects.stats must be a mapping.")
        stat_effects = {str(name): float(value) for name, value in stats_raw.items()}
        statuses[status_id] = StatusDefinition(
            id=status_id,
            label=label,
            description=description,
            icon=str(raw.get("icon", "")),
            applied_when=_parse_condition(raw.get("applied_when"), status_id, path),
            cleared_when=_parse_condition(raw.get("cleared_when"), status_id, path),
            stat_effects=stat_effects,
        )
    return statuses


def _load_juice(path: Path) -> JuiceSettings:
    payload = require_mapping(load_yaml_file(path), path)
    rate = payload.get("energy_recharge_rate")
    threshold = payload.get("recovery_threshold")
    table = payload.get("max_energy_per_level")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise ContentError(f"{path} has an invalid energy_recharge_rate {rate!r}.")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise ContentError(f"{path} has an invalid recovery_threshold {threshold!r}.")
    if not 0 < float(threshold) <= 1:
        raise ContentError(f"{path} recovery_threshold must be between 0 and 1.")
    if not isinstance(table, list) or not table:
        raise ContentError(f"{path} must define max_energy_per_level as a list.")
    values = tuple(int(value) for value in table)
    if any(value < 1 for value in values):
        raise ContentError(f"{path} max_energy_per_level entries must be positive.")
    return JuiceSettings(
        energy_recharge_rate=float(rate),
        recovery_threshold=float(threshold),
        max_energy_per_level=values,
    )


def _load_levels(path: Path) -> LevelTable:
    payload = require_mapping(load_yaml_file(path), path)
    levels: dict[int, LevelDefinition] = {}
    for raw_level, raw_entry in payload.items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError) as exc:
            raise ContentError(f"{path} has an invalid level '{raw_level}'.") from exc
        if not isinstance(raw_entry, dict):
            raise ContentError(f"{path} level {level} must define a mapping.")
        label = str(raw_entry.get("label", "")).strip()
        if not label:
            raise ContentError(f"{path} level {level} must define a label.")
        cap = raw_entry.get("max_equipped")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
            raise ContentError(f"{path} level {level} has an invalid max_equipped {cap!r}.")
        raw_kudos = raw_entry.get("kudos_to_next")
        if raw_kudos is None:
            kudos_to_next: int | None = None
        elif isinstance(raw_kudos, bool) or not isinstance(raw_kudos, int) or raw_kudos < 0:
            raise ContentError(f"{path} level {level} has an invalid kudos_to_next {raw_kudos!r}.")
        else:
            kudos_to_next = raw_kudos
        levels[level] = LevelDefinition(level=level, label=label, kudos_to_next=kudos_to_next, max_equipped=cap)
    if not levels:
        raise ContentError(f"{path} must define at least one level.")
    max_level = max(levels)
    for expected in range(max_level + 1):
        if expected not in levels:
            raise ContentError(f"{path} is missing level {expected}.")
    if levels[max_level].kudos_to_next is not None:
        raise ContentError(f"{path} maximum level {max_level} must not define kudos_to_next.")
    for level in range(max_level):
        if levels[level].kudos_to_next is None:
            raise ContentError(f"{path} level {level} must define kudos_to_next.")
    return LevelTable(levels=levels, max_level=max_level)


def _load_bops(path: Path) -> BopsSettings:
    payload = require_mapping(load_yaml_file(path), path)
    table = payload.get("daily_bops_per_level")
    if not isinstance(table, list) or not table:
        raise ContentError(f"{path} must define daily_bops_per_level as a list.")
    values = tuple(int(value) for value in table)
    if any(value < 0 for value in values):
        raise ContentError(f"{path} daily_bops_per_level entries must be non-negative.")
    cost = payload.get("sticker_swap_cost")
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
        raise ContentError(f"{path} has an invalid sticker_swap_cost {cost!r}.")
    return BopsSettings(daily_bops_per_level=values, sticker_swap_cost=cost)


def load_gameplay_content(core_path: Path) -> GameplayContent:
    """Load and validate all core gameplay settings from a content directory."""

    juice = _load_juice(core_path / "juice.yaml")
    levels = _load_levels(core_path / "levels.yaml")
    bops = _load_bops(core_path / "bops.yaml")
    expected_levels = levels.max_level + 1
    if len(juice.max_energy_per_level) < expected_levels:
        raise ContentError(
            f"{core_path / 'juice.yaml'} defines {len(juice.max_energy_per_level)} levels, "
            f"expected at least {expected_levels}."
        )
    if len(bops.daily_bops_per_level) < expected_levels:
        raise ContentError(
            f"{core_path / 'bops.yaml'} defines {len(bops.daily_bops_per_level)} levels, "
            f"expected at least {expected_levels}."
        )
    return GameplayContent(
        stats=_load_stats(core_path / "stats.yaml"),
        statuses=_load_statuses(core_path / "statuses.yaml"),
        juice=juice,
        levels=levels,
        bops=bops,
    )
