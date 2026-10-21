"""Vibe tuning shared by the classroom lesson and cafeteria rules."""

from __future__ import annotations

from collections.abc import Iterable


GRADE_VIBE_MIN = -1
GRADE_VIBE_MAX = 2
NICENESS_VIBE_MAX = 5
NICENESS_PER_PROP = 1
NICENESS_PER_UNIQUE_PROP = 2
NICENESS_DIVISOR = 5


def grade_vibe_delta(points: float) -> int:
    """Map mean grade points (A=4, B=3, C=2, D=1) to a student's vibe delta."""

    return max(GRADE_VIBE_MIN, min(GRADE_VIBE_MAX, round(float(points)) - 2))


def classroom_niceness_delta(prop_ids: Iterable[str]) -> int:
    """Return a capped 0..5 bonus from prop count and prop-type variety."""

    ids = [str(prop_id) for prop_id in prop_ids if prop_id]
    if not ids:
        return 0
    score = NICENESS_PER_PROP * len(ids) + NICENESS_PER_UNIQUE_PROP * len(set(ids))
    return min(NICENESS_VIBE_MAX, max(0, score // NICENESS_DIVISOR))
