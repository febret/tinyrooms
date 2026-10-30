"""Generic transient per-room override map."""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class TransientRoomMap(Generic[T]):
    """Track runtime overrides keyed by (room_id, instance_id)."""

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, str], T] = {}

    def set(self, room_id: str, instance_id: str, value: T) -> None:
        self._overrides[(room_id, instance_id)] = value

    def get(self, room_id: str, instance_id: str, default: T | None = None) -> T | None:
        return self._overrides.get((room_id, instance_id), default)

    def clear_room(self, room_id: str) -> None:
        for key in [key for key in self._overrides if key[0] == room_id]:
            del self._overrides[key]

    def clear(self) -> None:
        self._overrides.clear()
