"""Stateless room lighting resolution with a shared day-night cycle."""

from __future__ import annotations

import time

from server.content.lighting import (
    DEFAULT_LIGHTING_ENVIRONMENT,
    cycle_payload,
    cycle_phase,
    phase_to_environment,
)
from server.content.worlds import DIORAMA_BOARD_TYPE, WorldDefinition

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
    5. default ``"day"`` safety net for missing rooms
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

        Rooms with an authored ``dark`` flag, a per-room ``environment``, an
        explicit world ``environment``, or a diorama board (which owns its
        lighting) are pinned and never follow the cycle.
        """

        room = self._world.rooms.get(room_id)
        if room is None or room.dark or room.environment:
            return False
        if getattr(room, "board_type", "") == DIORAMA_BOARD_TYPE:
            return False
        return getattr(self._world, "environment", None) is None

    def mode(self, room_id: str) -> str:
        """Return ``cycle`` when the room follows the shared clock, else ``fixed``."""

        return "cycle" if self.follows_cycle(room_id) else "fixed"

    def poll_cycle_change(self) -> list[str] | None:
        """Return cycle-following rooms when the cycle bucket changed.

        Compares the current bucket against the last notified one, so repeated
        polls consume each bucket flip once. Returns ``None`` when the bucket
        is unchanged (or on the very first call, which only arms the baseline).
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
        world_environment = getattr(self._world, "environment", None)
        if isinstance(world_environment, str) and world_environment:
            return world_environment
        if room is None:
            return DEFAULT_LIGHTING_ENVIRONMENT
        return self.cycle_environment()

    def snapshot_payload(self, room_id: str, *, dark: bool | None = None) -> dict[str, object]:
        """Serialize the single resolved lighting state for a room.

        Every room carries the same shape: the effective preset plus whether it
        follows the shared clock, the shared cycle phase, and effective
        darkness. Diorama boards read the phase from here too, so there is no
        second top-level copy of the clock.
        """

        room = self._world.rooms.get(room_id)
        if dark is None:
            dark = room is not None and room.dark
        payload: dict[str, object] = {
            "name": self.environment_name(room_id, dark),
            **cycle_payload(time.time()),
            "mode": self.mode(room_id),
            "dark": bool(dark),
            "base_dark": bool(room is not None and room.dark),
        }
        return payload
