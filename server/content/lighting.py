"""Environment-based room lighting presets and resolution."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from server.content.common import ContentError


LIGHTING_ENVIRONMENTS = ("darkness", "night", "dusk", "day", "dawn")
DEFAULT_LIGHTING_ENVIRONMENT = "day"

# Single source of truth for the shared day-night cycle length, in seconds.
# The diorama board and the server-driven room presets use the same wall-clock
# epoch, so both stay in step. The client only keeps a fallback copy for rooms
# whose snapshot carries no duration (see board-diorama-daylight.js).
DAY_NIGHT_CYCLE_SECONDS = 600.0

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True, slots=True)
class LightingPreset:
    """Hand-authored lighting recipe for one named environment.

    This is the semantic half: color, level, and kind describe the light for
    gameplay and snapshots. Render tuning (light intensities, exposure) lives
    client-side in board-lighting.js, keyed by the same environment names.
    """

    name: str
    color: str
    level: float
    kind: str


PRESETS: dict[str, LightingPreset] = {
    "darkness": LightingPreset(name="darkness", color="#000000", level=0.0, kind="ambient"),
    "night": LightingPreset(name="night", color="#33456e", level=0.35, kind="moon"),
    "dusk": LightingPreset(name="dusk", color="#c98a6b", level=0.65, kind="directional"),
    "day": LightingPreset(name="day", color="#fff3d9", level=1.0, kind="directional"),
    "dawn": LightingPreset(name="dawn", color="#f7c9a0", level=0.75, kind="directional"),
}


def validate_lighting_name(raw_value: Any, label: str) -> str | None:
    """Validate an authored environment name, returning None when absent."""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ContentError(f"{label} must be a string.")
    name = raw_value.strip().lower()
    if not name:
        return None
    if name not in PRESETS:
        raise ContentError(
            f"{label} has unknown environment '{raw_value}'. "
            f"Expected one of {', '.join(LIGHTING_ENVIRONMENTS)}."
        )
    return name


def preset_for(name: str | None) -> LightingPreset:
    """Return the preset for *name*, falling back to the default."""

    if name in PRESETS:
        return PRESETS[name]
    return PRESETS[DEFAULT_LIGHTING_ENVIRONMENT]


def serialize_preset(preset: LightingPreset) -> dict[str, object]:
    """Serialize a preset for room snapshots."""

    if not _HEX_COLOR.match(preset.color):
        raise ContentError(f"Lighting preset '{preset.name}' has invalid color '{preset.color}'.")
    return {
        "name": preset.name,
        "color": preset.color,
        "level": float(preset.level),
        "type": preset.kind,
    }


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


def cycle_phase(seconds: float, duration: float = DAY_NIGHT_CYCLE_SECONDS) -> float:
    """Return the cycle phase in [0, 1) for a wall-clock timestamp."""

    if duration <= 0:
        return 0.0
    return ((float(seconds) % duration) / duration)
