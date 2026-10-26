"""Guard patrol, vision, and suspicion math for Tiny Vault heists."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class GuardState:
    """Mutable patrol and suspicion state for one staged guard."""

    peep_id: str
    room_id: str
    route: tuple[tuple[float, float], ...]
    waypoint_index: int = 0
    position: tuple[float, float] = (50.0, 50.0)
    facing: float = 0.0
    speed: float = 7.0
    pause_until: float = 0.0
    vision_range: float = 32.0
    vision_cone: float = 75.0
    state: str = "patrol"
    suspicion: float = 0.0
    last_seen: tuple[float, float] | None = None
    investigate_until: float = 0.0


def angle_to(source: tuple[float, float], target: tuple[float, float]) -> float:
    """Return the board bearing from *source* to *target* in degrees."""

    return math.degrees(math.atan2(target[1] - source[1], target[0] - source[0])) % 360.0


def angle_difference(first: float, second: float) -> float:
    """Return the smallest absolute difference between two bearings."""

    return abs((first - second + 180.0) % 360.0 - 180.0)


def can_see(
    guard_position: tuple[float, float],
    facing: float,
    target: tuple[float, float],
    vision_range: float,
    vision_cone: float,
    *,
    obscured: bool = False,
    visibility: float = 1.0,
) -> bool:
    """Return whether a target is inside a guard or camera vision cone."""

    if obscured or visibility <= 0.0:
        return False
    distance = math.hypot(target[0] - guard_position[0], target[1] - guard_position[1])
    if distance > max(1.0, vision_range * visibility):
        return False
    if distance < 4.0:
        return True
    return angle_difference(facing, angle_to(guard_position, target)) <= vision_cone / 2.0


def advance_patrol(guard: GuardState, now: float, delta: float) -> bool:
    """Move a guard toward its waypoint and report whether it is waiting."""

    if now < guard.pause_until or not guard.route:
        return False
    target = guard.route[guard.waypoint_index % len(guard.route)]
    delta_x = target[0] - guard.position[0]
    delta_y = target[1] - guard.position[1]
    distance = math.hypot(delta_x, delta_y)
    if distance < 0.75:
        guard.waypoint_index = (guard.waypoint_index + 1) % len(guard.route)
        guard.pause_until = now + 2.0
        return False
    step = min(distance, max(0.5, guard.speed * delta))
    guard.position = (
        guard.position[0] + delta_x / distance * step,
        guard.position[1] + delta_y / distance * step,
    )
    guard.facing = angle_to(guard.position, target)
    return True


def move_toward(guard: GuardState, target: tuple[float, float], speed: float, delta: float) -> None:
    """Move a guard toward an investigation or alarm position."""

    delta_x = target[0] - guard.position[0]
    delta_y = target[1] - guard.position[1]
    distance = math.hypot(delta_x, delta_y)
    if distance < 0.75:
        return
    step = min(distance, max(0.5, speed * delta))
    guard.position = (
        guard.position[0] + delta_x / distance * step,
        guard.position[1] + delta_y / distance * step,
    )
    guard.facing = angle_to(guard.position, target)


def suspicion_rate(distance: float, vision_range: float) -> float:
    """Return suspicion gained per second for a visible player."""

    closeness = max(0.0, 1.0 - distance / max(1.0, vision_range))
    return 8.0 + 22.0 * closeness
