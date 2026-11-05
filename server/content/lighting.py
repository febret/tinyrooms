"""Environment names, validation, and the shared day-night clock."""

from __future__ import annotations

from typing import Any

from server.content.common import ContentError

LIGHTING_ENVIRONMENTS = ("darkness", "night", "dusk", "day", "dawn", "fluorescent")
DEFAULT_LIGHTING_ENVIRONMENT = "day"

# Single source of truth for the shared day-night cycle length, in seconds.
# The diorama board and the server-driven room presets use the same wall-clock
# epoch, so both stay in step. The client only keeps a fallback copy for rooms
# whose snapshot carries no duration (see mods/tinytown/boards/daylight.js).
DAY_NIGHT_CYCLE_SECONDS = 600.0


def validate_lighting_name(raw_value: Any, label: str) -> str | None:
    """Validate an authored environment name, returning None when absent."""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ContentError(f"{label} must be a string.")
    name = raw_value.strip().lower()
    if not name:
        return None
    if name not in LIGHTING_ENVIRONMENTS:
        raise ContentError(
            f"{label} has unknown environment '{raw_value}'. "
            f"Expected one of {', '.join(LIGHTING_ENVIRONMENTS)}."
        )
    return name


def phase_to_environment(phase: float) -> str:
    """Map a day-cycle phase in [0, 1) to an environment name."""

    wrapped = ((float(phase) % 1.0) + 1.0) % 1.0
    if wrapped < 0.2 or wrapped >= 0.9:
        return "night"
    if wrapped < 0.3:
        return "dawn"
    if wrapped < 0.7:
        return "day"
    return "dusk"


def cycle_payload(seconds: float) -> dict[str, object]:
    """Return the shared day-cycle fields carried by every room snapshot."""

    return {
        "time_of_day": round(cycle_phase(seconds), 6),
        "day_cycle_seconds": DAY_NIGHT_CYCLE_SECONDS,
    }


def cycle_phase(seconds: float, duration: float = DAY_NIGHT_CYCLE_SECONDS) -> float:
    """Return the cycle phase in [0, 1) for a wall-clock timestamp."""

    if duration <= 0:
        return 0.0
    return ((float(seconds) % duration) / duration)


def cycle_index(seconds: float, duration: float = DAY_NIGHT_CYCLE_SECONDS) -> int:
    """Return which day-night cycle (counted from the wall-clock epoch) a timestamp is in."""

    if duration <= 0:
        return 0
    return int(float(seconds) // duration)


def cycle_remaining(seconds: float, duration: float = DAY_NIGHT_CYCLE_SECONDS) -> float:
    """Return the seconds left until the current cycle ends."""

    if duration <= 0:
        return 0.0
    return duration - (float(seconds) % duration)
