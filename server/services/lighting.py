"""Resolved environment lighting with an in-memory day-night override."""

from __future__ import annotations

import time

from server.content.lighting import (
    DAY_NIGHT_CYCLE_SECONDS,
    DEFAULT_LIGHTING_ENVIRONMENT,
    cycle_phase,
    phase_to_environment,
    preset_for,
    serialize_preset,
)
from server.content.worlds import WorldDefinition


WINDOW_TAG = "window"
FIXTURE_TAGS = frozenset({"lighting", "lamp", "lantern", "sconce"})
WINDOW_NIGHT_COLOR = "#8da7e8"
FIXTURE_LIGHT_COLOR = "#ffd9a1"


def prop_light_kind(definition: object) -> str | None:
    """Classify a prop definition as a window, fixture, or non-light."""

    tags = getattr(definition, "tags", ())
    normalized = {str(tag).lower() for tag in tags or ()}
    if WINDOW_TAG in normalized:
        return "window"
    if normalized & FIXTURE_TAGS:
        return "fixture"
    return None


def is_toggleable(definition: object) -> bool:
    """Return whether a prop definition has toggle behavior.

    Fixtures are currently the only toggleable kind: flipping them switches
    their light on or off. Anything else rejects `.toggle` with an error
    naming the prop, rather than guessing at a meaning.
    """

    return prop_light_kind(definition) == "fixture"


class LightingService:
    """Hold transient day-night overrides shared by all rooms in a world."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._overrides: dict[str, str] = {}

    def phase_now(self) -> float:
        """Return the current cycle phase in [0, 1).

        Uses the same wall-clock epoch as the diorama board so the town
        room and the server-driven room presets stay in sync.
        """

        return cycle_phase(time.time())

    def cycle_environment(self) -> str:
        """Resolve the current day-night environment from the shared phase."""

        return phase_to_environment(self.phase_now())

    def apply_cycle(self, room_ids: object = None) -> dict[str, str]:
        """Pin the current cycle environment on every inheriting room.

        Rooms with an authored ``environment`` or ``dark`` flag keep their
        specific setting; all others follow the shared phase. Returns the
        rooms whose override changed.
        """

        name = self.cycle_environment()
        candidates = list(room_ids) if room_ids is not None else list(self._world.rooms)
        changed: dict[str, str] = {}
        for room_id in candidates:
            room = self._world.rooms.get(room_id)
            if room is None or room.dark or room.environment:
                continue
            if self._overrides.get(room_id) != name:
                self._overrides[room_id] = name
                changed[room_id] = name
        return changed

    def snapshot_payload(self, room_id: str) -> dict[str, object]:
        """Serialize the resolved lighting plus the shared cycle phase."""

        payload = serialize_preset(preset_for(self._environment_name(room_id)))
        payload["time_of_day"] = round(self.phase_now(), 6)
        payload["day_cycle_seconds"] = DAY_NIGHT_CYCLE_SECONDS
        return payload

    def _environment_name(self, room_id: str) -> str:
        """Resolve the effective environment, honoring transient overrides."""

        room = self._world.rooms.get(room_id)
        if room is not None and room.dark:
            return "darkness"
        if room_id in self._overrides:
            return self._overrides[room_id]
        if room is not None and room.environment:
            return room.environment
        return getattr(self._world, "global_environment", DEFAULT_LIGHTING_ENVIRONMENT)
