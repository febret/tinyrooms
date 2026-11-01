"""Minimal circle collision helpers for activity controllers.

All arena obstacles are circles, so movement and projectile intersection both
reduce to distance checks. Anything fancier belongs in world content, not in
this module.
"""

from __future__ import annotations

import math
from typing import Any


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _radius(obstacle: dict[str, Any]) -> float:
    return _as_float(obstacle.get("r"))


def hits_obstacle(x: float, y: float, radius: float, obstacles: list[dict[str, Any]]) -> bool:
    """Return whether a circle at (*x*, *y*) touches any obstacle."""

    for obstacle in obstacles or []:
        if not isinstance(obstacle, dict):
            continue
        if math.hypot(x - _as_float(obstacle.get("x")), y - _as_float(obstacle.get("y"))) <= radius + _radius(obstacle):
            return True
    return False


def move_body(
    x: float,
    y: float,
    dx: float,
    dy: float,
    radius: float,
    arena: tuple[float, float],
    obstacles: list[dict[str, Any]],
) -> tuple[float, float]:
    """Slide a circle along one axis at a time so corners do not snag."""

    width, height = arena
    candidate_x = min(max(x + dx, radius), width - radius)
    if not hits_obstacle(candidate_x, y, radius, obstacles):
        x = candidate_x
    candidate_y = min(max(y + dy, radius), height - radius)
    if not hits_obstacle(x, candidate_y, radius, obstacles):
        y = candidate_y
    return x, y


def sweep_hits_obstacle(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    obstacles: list[dict[str, Any]],
) -> bool:
    """Return whether the segment from (*x1*, *y1*) to (*x2*, *y2*) clips an obstacle."""

    for obstacle in obstacles or []:
        if not isinstance(obstacle, dict):
            continue
        cx, cy = _as_float(obstacle.get("x")), _as_float(obstacle.get("y"))
        limit = radius + _radius(obstacle)
        dx, dy = x2 - x1, y2 - y1
        length_squared = dx * dx + dy * dy
        if length_squared < 1e-9:
            if math.hypot(x1 - cx, y1 - cy) <= limit:
                return True
            continue
        elapsed = max(0.0, min(1.0, ((cx - x1) * dx + (cy - y1) * dy) / length_squared))
        if math.hypot(x1 + elapsed * dx - cx, y1 + elapsed * dy - cy) <= limit:
            return True
    return False
