"""Shared 3D integer room-grid geometry and free-space allocation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.content.common import ContentError, require_int


DIRECTION_VECTORS: dict[str, tuple[int, int, int]] = {
    "north": (0, -1, 0),
    "south": (0, 1, 0),
    "east": (-1, 0, 0),
    "west": (1, 0, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}
DIRECTION_TRANSITIONS = {name: f"swipe-{name}" for name in DIRECTION_VECTORS}
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


def parse_room_grid(raw_value: Any, room_id: str) -> tuple[int, int, int] | None:
    """Validate an optional authored ``grid: [x, y, z]`` room coordinate."""

    if raw_value is None:
        return None
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
        raise ContentError(f"Room '{room_id}' grid must be a list of three integers [x, y, z].")
    return tuple(
        require_int(value, f"Room '{room_id}' grid coordinate", INT32_MIN, INT32_MAX)
        for value in raw_value
    )


def add_coordinates(
    position: tuple[int, int, int], vector: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Add a direction vector while keeping coordinates inside int32 range."""

    point = (position[0] + vector[0], position[1] + vector[1], position[2] + vector[2])
    if any(not INT32_MIN <= value <= INT32_MAX for value in point):
        raise ContentError(f"Room grid position {point} is outside the int32 range.")
    return point


def direction_between(
    source: tuple[int, int, int] | None, target: tuple[int, int, int] | None
) -> str | None:
    """Return the conventional direction from *source* to *target*, if adjacent."""

    if source is None or target is None:
        return None
    delta = (target[0] - source[0], target[1] - source[1], target[2] - source[2])
    for name, vector in DIRECTION_VECTORS.items():
        if delta == vector:
            return name
    return None


def room_grid_enabled(rooms: Mapping[str, Any]) -> bool:
    """Return whether any live room already has a grid position."""

    return any(
        getattr(room, "grid", None) is not None and not getattr(room, "template", False)
        for room in rooms.values()
    )


def occupied_grid_positions(rooms: Mapping[str, Any]) -> set[tuple[int, int, int]]:
    """Return every assigned non-template grid coordinate in *rooms*."""

    positions: set[tuple[int, int, int]] = set()
    for room in rooms.values():
        position = getattr(room, "grid", None)
        if position is not None and not getattr(room, "template", False):
            positions.add((position[0], position[1], position[2]))
    return positions


def extend_grid_cluster(
    rooms: Mapping[str, Any],
    seeds: list[tuple[int, int, int]],
    count: int,
) -> list[tuple[int, int, int]]:
    """Find up to *count* free cells orthogonally adjacent to *seeds*.

    Candidates stay in deterministic seed/direction order and never touch an
    occupied cell outside the seed cluster, so growing a house or gallery
    keeps the new rooms connected to their existing cluster without linking
    to unrelated rooms. Returns fewer than *count* cells when no more fit.
    """

    occupied = occupied_grid_positions(rooms)
    seeds_set = set(seeds)
    placed: list[tuple[int, int, int]] = []
    for seed in seeds:
        for vector in DIRECTION_VECTORS.values():
            if len(placed) >= count:
                return placed
            candidate = (seed[0] + vector[0], seed[1] + vector[1], seed[2] + vector[2])
            if candidate in occupied or candidate in seeds_set or candidate in placed:
                continue
            if not all(INT32_MIN <= value <= INT32_MAX for value in candidate):
                continue
            neighbors = {
                (candidate[0] + dx, candidate[1] + dy, candidate[2] + dz)
                for dx, dy, dz in DIRECTION_VECTORS.values()
            }
            if any(
                neighbor in occupied and neighbor not in seeds_set for neighbor in neighbors
            ):
                continue
            placed.append(candidate)
    return placed


def allocate_grid_block(
    rooms: Mapping[str, Any],
    count: int,
    *,
    origin: tuple[int, int, int] = (0, 0, 0),
    columns: int = 3,
    margin: int = 1,
    search_limit: int = 512,
) -> list[tuple[int, int, int]]:
    """Find the first free connected rectangular block of *count* grid cells.

    The search is a deterministic first fit scanning +x then +y from *origin*
    at a fixed z, so persisted dynamic rooms can be recomputed in the same
    order after a restart without storing their coordinates. The margin is
    three-dimensional: separately allocated blocks never touch, including
    vertically.
    """

    if count < 1:
        raise ContentError("Room-grid allocation needs at least one room.")
    if margin < 0:
        raise ContentError("Room-grid allocation margin cannot be negative.")
    width = max(1, min(int(columns), count))
    rows = (count + width - 1) // width
    occupied = occupied_grid_positions(rooms)
    for delta_y in range(search_limit):
        for delta_x in range(search_limit):
            anchor = (origin[0] + delta_x, origin[1] + delta_y, origin[2])
            block = [
                (anchor[0] + column, anchor[1] + row, anchor[2])
                for row in range(rows)
                for column in range(width)
            ][:count]
            if not all(INT32_MIN <= value <= INT32_MAX for point in block for value in point):
                continue
            buffered = {
                (point[0] + dx, point[1] + dy, point[2] + dz)
                for point in block
                for dx in range(-margin, margin + 1)
                for dy in range(-margin, margin + 1)
                for dz in range(-margin, margin + 1)
            }
            if all(point not in occupied for point in buffered):
                return block
    raise ContentError("No free room-grid space was found for dynamic rooms.")
