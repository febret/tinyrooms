"""In-memory per-instance active prop-effect selection.

Effect *definitions* and each prop's default active set live in YAML; this
service only tracks runtime switches made through the service API. The state
is intentionally transient: a process restart, or a world reload that drops
the room, falls back to the authored default.
"""

from __future__ import annotations


class RoomEffectService:
    """Track the active effect set chosen for each prop instance."""

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, str], str] = {}

    def set(self, room_id: str, prop_instance_id: str, set_name: str) -> None:
        """Record a runtime active-set choice for one prop instance."""

        self._overrides[(room_id, prop_instance_id)] = set_name

    def active_for(self, room_id: str, prop_instance_id: str, default: str | None) -> str | None:
        """Return the runtime override, or the authored default when none."""

        return self._overrides.get((room_id, prop_instance_id), default)

    def clear_room(self, room_id: str) -> None:
        """Drop every override for a room (e.g. when its rooms are re-seeded)."""

        for key in [key for key in self._overrides if key[0] == room_id]:
            del self._overrides[key]

    def clear(self) -> None:
        """Drop every override (e.g. on a full world reload)."""

        self._overrides.clear()
