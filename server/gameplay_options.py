"""Gameplay option loading and validation for a Tinyrooms world server.

An options file lets an operator tune the shipped survival mechanics and their
constants without editing authored content. Missing values keep the current
core defaults; unknown keys are rejected so typos cannot silently do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
import tempfile
from pathlib import Path

from server.content.gameplay import GameplayContent


OPTIONS_VERSION = 1
DEFAULT_MAX_ENERGY_PER_LEVEL = (
    80,
    100,
    110,
    120,
    130,
    140,
    155,
    170,
    185,
    200,
    220,
    240,
    260,
    280,
    300,
    330,
)
STATUS_MECHANICS = {
    "tired": "energy",
    "sick": "sickness",
    "stinky": "cleanliness",
}
DROP_STATUSES = {
    "sick": "sickness",
    "stinky": "cleanliness",
}


class GameplayOptionsError(ValueError):
    """Raised when an options file cannot be read or validated."""


@dataclass(frozen=True, slots=True)
class MechanicsOptions:
    """Toggles for the shipped survival mechanics."""

    energy: bool = True
    sickness: bool = True
    cleanliness: bool = True


@dataclass(frozen=True, slots=True)
class CardDropOptions:
    """Per-status toggles for dynamic card drops."""

    sickness: bool = True
    cleanliness: bool = True


@dataclass(frozen=True, slots=True)
class GameplayConstants:
    """Gameplay constants that options may override."""

    # Energy restored per minute while offline or online.
    energy_recharge_rate: float = 1.0
    # Fraction of maximum Energy required to clear Tired after reaching zero.
    energy_recovery_threshold: float = 0.1
    # Base maximum Energy indexed by user level; must cover every core level.
    max_energy_per_level: tuple[int, ...] = DEFAULT_MAX_ENERGY_PER_LEVEL
    # Baseline maximum Health before Constitution and Health modifiers.
    base_max_health: int = 50
    # Baseline maximum Cleanliness before Cleanliness modifiers.
    base_max_cleanliness: int = 100
    # Default Energy cost for ordinary cards without an explicit cost.
    energy_cost_card: int = 2
    # Energy cost for Expression emotes.
    energy_cost_expression: int = 1
    # Energy cost for Animation emotes.
    energy_cost_animation: int = 2
    # Energy cost for Cutscene emotes.
    energy_cost_cutscene_emote: int = 5
    # Energy cost for moving between rooms.
    energy_cost_room_change: int = 1
    # Energy cost for sending a chat message.
    energy_cost_chat: int = 1
    # Per-check chance that each status-carrying peep mints a dynamic drop.
    dynamic_card_drop_chance: float = 0.1
    # Minimum seconds between dynamic drop checks for a room.
    dynamic_card_check_seconds: float = 60.0
    # Maximum dynamic card stacks allowed in one room.
    max_dynamic_room_stacks: int = 10
    # Vibe change applied from each non-stinky peep to a stinky peep per check.
    stinky_vibe_delta: int = -1
    # Neutral Charisma baseline; each point above or below shifts vibes.
    charisma_vibe_base: int = 1
    # Seconds between room vibe and stinky status rule checks.
    vibe_check_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class GameplayOptions:
    """A validated gameplay options snapshot."""

    mechanics: MechanicsOptions = field(default_factory=MechanicsOptions)
    card_drops: CardDropOptions = field(default_factory=CardDropOptions)
    constants: GameplayConstants = field(default_factory=GameplayConstants)
    version: int = OPTIONS_VERSION

    @property
    def energy_enabled(self) -> bool:
        return self.mechanics.energy

    @property
    def sickness_enabled(self) -> bool:
        return self.mechanics.sickness

    @property
    def cleanliness_enabled(self) -> bool:
        return self.mechanics.cleanliness

    def status_enabled(self, status_id: str) -> bool:
        """Return whether a status may be applied under these options."""

        mechanic = STATUS_MECHANICS.get(status_id)
        if mechanic is None:
            return True
        return bool(getattr(self.mechanics, mechanic))

    def suppressed_statuses(self) -> frozenset[str]:
        """Return status ids disabled by the mechanic toggles."""

        return frozenset(
            status_id for status_id in STATUS_MECHANICS if not self.status_enabled(status_id)
        )

    def counter_enabled(self, counter: str) -> bool:
        """Return whether a core counter may change under these options."""

        if counter == "energy":
            return self.energy_enabled
        if counter == "health":
            return self.sickness_enabled
        if counter == "cleanliness":
            return self.cleanliness_enabled
        return True

    def drop_enabled(self, status_id: str) -> bool:
        """Return whether dynamic card drops may use *status_id*."""

        mechanic = DROP_STATUSES.get(status_id)
        if mechanic is None:
            return True
        return self.status_enabled(status_id) and bool(getattr(self.card_drops, mechanic))

    def to_dict(self) -> dict[str, object]:
        """Serialize for an options file or Mission Control."""

        return {
            "version": self.version,
            "mechanics": {
                "energy": self.mechanics.energy,
                "sickness": self.mechanics.sickness,
                "cleanliness": self.mechanics.cleanliness,
            },
            "card_drops": {
                "sickness": self.card_drops.sickness,
                "cleanliness": self.card_drops.cleanliness,
            },
            "constants": {
                "energy_recharge_rate": self.constants.energy_recharge_rate,
                "energy_recovery_threshold": self.constants.energy_recovery_threshold,
                "max_energy_per_level": list(self.constants.max_energy_per_level),
                "base_max_health": self.constants.base_max_health,
                "base_max_cleanliness": self.constants.base_max_cleanliness,
                "energy_cost_card": self.constants.energy_cost_card,
                "energy_cost_expression": self.constants.energy_cost_expression,
                "energy_cost_animation": self.constants.energy_cost_animation,
                "energy_cost_cutscene_emote": self.constants.energy_cost_cutscene_emote,
                "energy_cost_room_change": self.constants.energy_cost_room_change,
                "energy_cost_chat": self.constants.energy_cost_chat,
                "dynamic_card_drop_chance": self.constants.dynamic_card_drop_chance,
                "dynamic_card_check_seconds": self.constants.dynamic_card_check_seconds,
                "max_dynamic_room_stacks": self.constants.max_dynamic_room_stacks,
                "stinky_vibe_delta": self.constants.stinky_vibe_delta,
                "charisma_vibe_base": self.constants.charisma_vibe_base,
                "vibe_check_seconds": self.constants.vibe_check_seconds,
            },
        }


DEFAULT_GAMEPLAY_OPTIONS = GameplayOptions()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GameplayOptionsError(f"{label} must be a JSON object.")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise GameplayOptionsError(f"{label} must be true or false.")
    return value


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GameplayOptionsError(f"{label} must be a number.")
    number = float(value)
    if positive and number <= 0:
        raise GameplayOptionsError(f"{label} must be positive.")
    return number


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GameplayOptionsError(f"{label} must be an integer.")
    number = float(value)
    if not number.is_integer():
        raise GameplayOptionsError(f"{label} must be an integer.")
    result = int(number)
    if minimum is not None and result < minimum:
        raise GameplayOptionsError(f"{label} must be at least {minimum}.")
    return result


def _reject_unknown(payload: dict[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise GameplayOptionsError(f"{label} contains unknown fields: {', '.join(unknown)}.")


def _parse_mechanisms(payload: object) -> MechanicsOptions:
    data = _mapping(payload if payload is not None else {}, "mechanics")
    _reject_unknown(data, {"energy", "sickness", "cleanliness"}, "mechanics")
    defaults = MechanicsOptions()
    return MechanicsOptions(
        energy=_bool(data["energy"], "mechanics.energy") if "energy" in data else defaults.energy,
        sickness=_bool(data["sickness"], "mechanics.sickness") if "sickness" in data else defaults.sickness,
        cleanliness=(
            _bool(data["cleanliness"], "mechanics.cleanliness")
            if "cleanliness" in data
            else defaults.cleanliness
        ),
    )


def _parse_card_drops(payload: object) -> CardDropOptions:
    data = _mapping(payload if payload is not None else {}, "card_drops")
    _reject_unknown(data, {"sickness", "cleanliness"}, "card_drops")
    defaults = CardDropOptions()
    return CardDropOptions(
        sickness=(
            _bool(data["sickness"], "card_drops.sickness")
            if "sickness" in data
            else defaults.sickness
        ),
        cleanliness=(
            _bool(data["cleanliness"], "card_drops.cleanliness")
            if "cleanliness" in data
            else defaults.cleanliness
        ),
    )


def _parse_constants(payload: object) -> GameplayConstants:
    data = _mapping(payload if payload is not None else {}, "constants")
    defaults = GameplayConstants()
    allowed = set(defaults.__dataclass_fields__)
    _reject_unknown(data, allowed, "constants")

    raw_table = data.get("max_energy_per_level", defaults.max_energy_per_level)
    if not isinstance(raw_table, (list, tuple)) or not raw_table:
        raise GameplayOptionsError("constants.max_energy_per_level must be a non-empty list.")
    table = tuple(
        _integer(value, "constants.max_energy_per_level entries", minimum=1)
        for value in raw_table
    )

    def number(name: str, *, positive: bool = False) -> float:
        if name not in data:
            return float(getattr(defaults, name))
        return _number(data[name], f"constants.{name}", positive=positive)

    def integer(name: str, *, minimum: int | None = None) -> int:
        if name not in data:
            return int(getattr(defaults, name))
        return _integer(data[name], f"constants.{name}", minimum=minimum)

    threshold = number("energy_recovery_threshold")
    if not 0 < threshold <= 1:
        raise GameplayOptionsError("constants.energy_recovery_threshold must be between 0 and 1.")
    drop_chance = number("dynamic_card_drop_chance")
    if not 0 <= drop_chance <= 1:
        raise GameplayOptionsError("constants.dynamic_card_drop_chance must be between 0 and 1.")

    return GameplayConstants(
        energy_recharge_rate=number("energy_recharge_rate", positive=True),
        energy_recovery_threshold=threshold,
        max_energy_per_level=table,
        base_max_health=integer("base_max_health", minimum=1),
        base_max_cleanliness=integer("base_max_cleanliness", minimum=1),
        energy_cost_card=integer("energy_cost_card", minimum=0),
        energy_cost_expression=integer("energy_cost_expression", minimum=0),
        energy_cost_animation=integer("energy_cost_animation", minimum=0),
        energy_cost_cutscene_emote=integer("energy_cost_cutscene_emote", minimum=0),
        energy_cost_room_change=integer("energy_cost_room_change", minimum=0),
        energy_cost_chat=integer("energy_cost_chat", minimum=0),
        dynamic_card_drop_chance=drop_chance,
        dynamic_card_check_seconds=number("dynamic_card_check_seconds", positive=True),
        max_dynamic_room_stacks=integer("max_dynamic_room_stacks", minimum=0),
        stinky_vibe_delta=integer("stinky_vibe_delta"),
        charisma_vibe_base=integer("charisma_vibe_base"),
        vibe_check_seconds=number("vibe_check_seconds", positive=True),
    )


def parse_gameplay_options(payload: object) -> GameplayOptions:
    """Validate and normalize an options mapping, filling omitted defaults."""

    if payload is None:
        return DEFAULT_GAMEPLAY_OPTIONS
    data = _mapping(payload, "options")
    _reject_unknown(data, {"version", "mechanics", "card_drops", "constants"}, "options")
    version = data.get("version", OPTIONS_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version != OPTIONS_VERSION:
        raise GameplayOptionsError(f"options.version must be {OPTIONS_VERSION}.")
    return GameplayOptions(
        mechanics=_parse_mechanisms(data.get("mechanics")),
        card_drops=_parse_card_drops(data.get("card_drops")),
        constants=_parse_constants(data.get("constants")),
        version=version,
    )


def load_gameplay_options(path: Path | None) -> GameplayOptions:
    """Load an options file, returning defaults when no path is configured."""

    if path is None:
        return DEFAULT_GAMEPLAY_OPTIONS
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GameplayOptionsError(f"Gameplay options file does not exist: {path}") from exc
    except (OSError, ValueError) as exc:
        raise GameplayOptionsError(f"Gameplay options file could not be read: {path}") from exc
    return parse_gameplay_options(payload)


def write_gameplay_options(path: Path, options: GameplayOptions) -> None:
    """Atomically write a normalized options file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(options.to_dict(), indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=".options-", dir=str(target.parent), text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass


def apply_gameplay_options(
    content: GameplayContent,
    options: GameplayOptions,
) -> GameplayContent:
    """Return content with option constants applied on top of authored values."""

    constants = options.constants
    expected_levels = content.levels.max_level + 1
    if len(constants.max_energy_per_level) < expected_levels:
        raise GameplayOptionsError(
            "constants.max_energy_per_level must define at least "
            f"{expected_levels} entries for this world."
        )
    juice = replace(
        content.juice,
        energy_recharge_rate=constants.energy_recharge_rate,
        recovery_threshold=constants.energy_recovery_threshold,
        max_energy_per_level=constants.max_energy_per_level,
    )
    statuses = content.statuses
    tired = statuses.get("tired")
    if tired is not None and tired.cleared_when is not None:
        statuses = dict(statuses)
        statuses["tired"] = replace(
            tired,
            cleared_when=replace(
                tired.cleared_when,
                at_or_above_fraction=constants.energy_recovery_threshold,
            ),
        )
    return replace(
        content,
        juice=juice,
        statuses=statuses,
        base_max_health=constants.base_max_health,
        base_max_cleanliness=constants.base_max_cleanliness,
    )
