"""Server-authoritative floor placement for NPC peeps in sprite-mode rooms."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable

from server.content.worlds import PropInstanceDefinition, WorldDefinition


BOARD_X_PER_PERCENT = 0.105
BOARD_Z_PER_PERCENT = 0.085
SPRITE_EDGE_MARGIN = 6.0
SPRITE_RADIUS = 0.24
SPRITE_SEPARATION = 0.42
DEFAULT_FOOTPRINT = 2.5
RANDOM_ATTEMPTS = 64
GRID_STEPS = 18


@dataclass(frozen=True, slots=True)
class SpriteBlock:
    """A rotated prop footprint in board world coordinates."""

    x: float
    z: float
    half_x: float
    half_z: float


def _world_point(position: Iterable[float]) -> tuple[float, float]:
    values = list(position)
    x = float(values[0]) if values else 50.0
    y = float(values[1]) if len(values) > 1 else 50.0
    return (x - 50.0) * BOARD_X_PER_PERCENT, (y - 50.0) * BOARD_Z_PER_PERCENT


def _percent_point(x: float, z: float) -> tuple[float, float]:
    return x / BOARD_X_PER_PERCENT + 50.0, z / BOARD_Z_PER_PERCENT + 50.0


def _prop_block(
    world: WorldDefinition,
    instance: PropInstanceDefinition,
) -> SpriteBlock:
    """Build a rotation-aware footprint for one placed prop."""

    definition = world.props.get(instance.prop_id)
    footprint = definition.sprite_footprint if definition is not None else None
    if footprint is None:
        scale = definition.scale if definition is not None else 1.0
        footprint = (DEFAULT_FOOTPRINT * scale, DEFAULT_FOOTPRINT * scale)
    half_x = float(footprint[0]) * instance.scale * BOARD_X_PER_PERCENT
    half_z = float(footprint[1]) * instance.scale * BOARD_Z_PER_PERCENT
    angle = math.radians(instance.rot[1]) if len(instance.rot) > 1 else 0.0
    cos = abs(math.cos(angle))
    sin = abs(math.sin(angle))
    center_x, center_z = _world_point(instance.pos)
    return SpriteBlock(
        x=center_x,
        z=center_z,
        half_x=cos * half_x + sin * half_z,
        half_z=sin * half_x + cos * half_z,
    )


class SpriteService:
    """Assigns static, random 2D sprite positions for NPCs.

    Positions are intentionally in memory: entering a room (or restarting the
    process) gives a fresh random valid spot. Sprites never move within a room.
    Only this service writes the map.
    """

    def __init__(
        self,
        world: WorldDefinition,
        *,
        layout: object | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._world = world
        self._layout = layout
        self._rng = rng or random.Random()
        self._npc_positions: dict[str, tuple[str, tuple[float, float]]] = {}

    def enabled(self, room_id: str) -> bool:
        """Return whether *room_id* opts into sprite mode."""

        room = self._world.rooms.get(room_id)
        return bool(room is not None and room.sprites_enabled)

    def _props(self, room_id: str) -> list[PropInstanceDefinition]:
        if self._layout is not None and hasattr(self._layout, "effective_props"):
            return list(self._layout.effective_props(room_id))
        room = self._world.rooms[room_id]
        return list(room.props.values())

    def _blocks(self, room_id: str) -> list[SpriteBlock]:
        return [_prop_block(self._world, prop) for prop in self._props(room_id)]

    def _positions_in(self, room_id: str) -> list[tuple[float, float]]:
        return [
            _world_point(position)
            for stored_room, position in self._npc_positions.values()
            if stored_room == room_id
        ]

    @staticmethod
    def _inside_bounds(x: float, z: float) -> bool:
        min_x, _ = _world_point((SPRITE_EDGE_MARGIN, 50.0))
        max_x, _ = _world_point((100.0 - SPRITE_EDGE_MARGIN, 50.0))
        _, min_z = _world_point((50.0, SPRITE_EDGE_MARGIN))
        _, max_z = _world_point((50.0, 100.0 - SPRITE_EDGE_MARGIN))
        return min_x <= x <= max_x and min_z <= z <= max_z

    def _valid(
        self,
        x: float,
        z: float,
        blocks: list[SpriteBlock],
        occupied: list[tuple[float, float]],
    ) -> bool:
        if not self._inside_bounds(x, z):
            return False
        for block in blocks:
            if (
                abs(x - block.x) < block.half_x + SPRITE_RADIUS
                and abs(z - block.z) < block.half_z + SPRITE_RADIUS
            ):
                return False
        for other_x, other_z in occupied:
            if math.hypot(x - other_x, z - other_z) < SPRITE_SEPARATION:
                return False
        return True

    def _place(self, room_id: str) -> tuple[float, float] | None:
        blocks = self._blocks(room_id)
        occupied = self._positions_in(room_id)
        min_x, _ = _world_point((SPRITE_EDGE_MARGIN, 50.0))
        max_x, _ = _world_point((100.0 - SPRITE_EDGE_MARGIN, 50.0))
        _, min_z = _world_point((50.0, SPRITE_EDGE_MARGIN))
        _, max_z = _world_point((50.0, 100.0 - SPRITE_EDGE_MARGIN))
        for _ in range(RANDOM_ATTEMPTS):
            x = self._rng.uniform(min_x, max_x)
            z = self._rng.uniform(min_z, max_z)
            if self._valid(x, z, blocks, occupied):
                return _percent_point(x, z)
        for row in range(GRID_STEPS):
            z = min_z + (max_z - min_z) * (row + 0.5) / GRID_STEPS
            for column in range(GRID_STEPS):
                x = min_x + (max_x - min_x) * (column + 0.5) / GRID_STEPS
                if self._valid(x, z, blocks, occupied):
                    return _percent_point(x, z)
        return None

    def forget_npc(self, peep_id: str) -> None:
        """Discard an NPC's stored position after it changes rooms."""

        self._npc_positions.pop(peep_id, None)

    def ensure_npc(self, peep_id: str, room_id: str) -> tuple[float, float] | None:
        """Return an NPC's static sprite position, assigning one on first entry."""

        if not self.enabled(room_id):
            return None
        stored = self._npc_positions.get(peep_id)
        if stored is not None and stored[0] == room_id:
            return stored[1]
        position = self._place(room_id)
        if position is None:
            return None
        self._npc_positions[peep_id] = (room_id, position)
        return position
