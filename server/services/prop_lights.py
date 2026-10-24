"""Transient per-instance light-fixture on/off state."""

from __future__ import annotations


class PropLightService:
    """Track whether a light-fixture prop instance is switched on."""

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, str], bool] = {}

    def is_on(self, room_id: str, prop_instance_id: str, default: bool = True) -> bool:
        """Return the runtime override, defaulting to on."""

        return self._overrides.get((room_id, prop_instance_id), default)

    def toggle(self, room_id: str, prop_instance_id: str, default: bool = True) -> bool:
        """Flip the runtime state and return the new value."""

        value = not self.is_on(room_id, prop_instance_id, default)
        self._overrides[(room_id, prop_instance_id)] = value
        return value
