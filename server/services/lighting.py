"""Stateless room lighting resolution with a shared day-night cycle."""

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
    """Resolve room lighting from YAML overrides, falling back to the day-night cycle.

    Resolution order (top wins):

    1. effective ``dark`` (authored ``room.dark`` or a runtime darkness
       override passed in as ``dark=True``) -> ``"darkness"``
    2. per-room ``rooms.yaml`` ``environment`` (persistent author override)
    3. explicit world ``world.yaml`` ``environment`` (persistent author
       override that freezes the cycle for the whole world; worlds that omit
       the key keep cycling)
    4. live day-night cycle bucket for the shared wall-clock phase
    5. ``world.global_environment`` / default ``"day"`` safety net
    """

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._notified_bucket: str | None = None

    def phase_now(self) -> float:
        """Return the current cycle phase in [0, 1).

        Uses the same wall-clock epoch as the diorama board so the town
        room and the server-driven room presets stay in sync.
        """

        return cycle_phase(time.time())

    def cycle_environment(self) -> str:
        """Resolve the current day-night environment from the shared phase."""

        return phase_to_environment(self.phase_now())

    def follows_cycle(self, room_id: str) -> bool:
        """Return whether a room tracks the live day-night cycle.

        Rooms with an authored ``dark`` flag, a per-room ``environment``, or
        an explicit world ``environment`` are pinned and never follow the
        cycle. Everything else inherits the current cycle bucket.
        """

        room = self._world.rooms.get(room_id)
        if room is None or room.dark or room.environment:
            return False
        return getattr(self._world, "global_environment_override", None) is None

    def poll_cycle_change(self) -> list[str] | None:
        """Return cycle-following rooms when the cycle bucket changed.

        Compares the current bucket against the last notified one, so the
        ticker hook and the TinyTown mod driver can share one instance
        without double-broadcasting: the first caller consumes the change
        and later callers see ``None`` until the next bucket flip. Returns
        ``None`` when the bucket is unchanged (or on the very first call,
        which only arms the baseline without fanning out).
        """

        current = self.cycle_environment()
        if current == self._notified_bucket:
            return None
        first_poll = self._notified_bucket is None
        self._notified_bucket = current
        if first_poll:
            return None
        return [room_id for room_id in self._world.rooms if self.follows_cycle(room_id)]

    def environment_name(self, room_id: str, dark: bool | None = None) -> str:
        """Resolve the effective environment name for a room.

        *dark* is the effective room darkness (for example from a dynamic
        lighting override). When omitted, the authored ``room.dark`` flag
        is used.
        """

        room = self._world.rooms.get(room_id)
        if dark is None:
            dark = room is not None and room.dark
        if dark:
            return "darkness"
        if room is not None and room.environment:
            return room.environment
        override = getattr(self._world, "global_environment_override", None)
        if isinstance(override, str) and override:
            return override
        if room is None:
            return getattr(self._world, "global_environment", DEFAULT_LIGHTING_ENVIRONMENT)
        return self.cycle_environment()

    def snapshot_payload(self, room_id: str, *, dark: bool | None = None) -> dict[str, object]:
        """Serialize the resolved lighting plus the shared cycle phase.

        *dark* is the effective room darkness (for example from a dynamic
        lighting override). When omitted, the authored ``room.dark`` flag is
        used, preserving the previous behavior.
        """

        payload = serialize_preset(preset_for(self.environment_name(room_id, dark)))
        payload["time_of_day"] = round(self.phase_now(), 6)
        payload["day_cycle_seconds"] = DAY_NIGHT_CYCLE_SECONDS
        return payload
