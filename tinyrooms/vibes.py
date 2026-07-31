"""Vibe system: baseline scores, descriptors, decay, and runtime queries.

A vibe is a float score (-100..100) representing how a source peep feels about
a target peep.  0 means the target is unknown to the source.  Scores can
exceed this range internally but are clamped for display/gameplay purposes.

Baseline vibes are persisted in the ``vibes`` column of the worldstate
``peeps`` table as a JSON object mapping target-peep-id to float score.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .peep import Peep
    from .room import Room
    from .world import World

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VISIBLE_MIN: float = -100.0
VISIBLE_MAX: float = 100.0
DEFAULT_DECAY_PER_MINUTE: float = 0.1

# Epsilon used when removing near-zero vibe entries
_ZERO_EPSILON: float = 1e-9

# ---------------------------------------------------------------------------
# Descriptor bands
# Positive: 1-25 Friend, 26-50 Buddy, 51-75 BFF, 76-100 Supreme BFF
# Negative: -1..-25 Annoyance, -26..-50 Enemy, -51..-75 Nemesis, -76..-100 Archnemesis
# 0: unknown (entry should be removed)
# ---------------------------------------------------------------------------

_POSITIVE_BANDS = [
    (76, 100, "Supreme BFF 😍"),
    (51, 75, "BFF 🥰"),
    (26, 50, "Buddy 😃"),
    (1, 25, "Friend 🙂"),
]

_NEGATIVE_BANDS = [
    (-100, -76, "Archnemesis 👿"),
    (-75, -51, "Nemesis 😡"),
    (-50, -26, "Enemy 😤"),
    (-25, -1, "Annoyance 🙄"),
]


# ---------------------------------------------------------------------------
# Utility API
# ---------------------------------------------------------------------------

def clamp_visible(v: float) -> float:
    """Clamp *v* to the visible range [VISIBLE_MIN, VISIBLE_MAX]."""
    return max(VISIBLE_MIN, min(VISIBLE_MAX, float(v)))


def normalize_vibe_map(value) -> dict[str, float]:
    """Return a clean ``{target_peep_id: float}`` dict from any raw input.

    Unknown / malformed entries are dropped; entries with score exactly 0 are
    also dropped (per spec: 0 means unknown).
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k:
            continue
        try:
            score = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(score) or math.isinf(score):
            continue
        if abs(score) > _ZERO_EPSILON:
            result[k] = score
    return result


def get_baseline(source_peep: 'Peep', target_peep_id: str) -> float:
    """Return the baseline vibe score of *source_peep* toward *target_peep_id*.

    Returns 0.0 if no record exists (unknown).
    """
    return getattr(source_peep, 'vibes', {}).get(target_peep_id, 0.0)


def set_baseline(source_peep: 'Peep', target_peep_id: str, value: float) -> None:
    """Set the baseline vibe of *source_peep* toward *target_peep_id* to *value*.

    If *value* is effectively zero the entry is removed (unknown semantics).
    """
    if not hasattr(source_peep, 'vibes'):
        source_peep.vibes = {}
    if abs(value) <= _ZERO_EPSILON:
        source_peep.vibes.pop(target_peep_id, None)
    else:
        source_peep.vibes[target_peep_id] = value


def apply_baseline_delta(source_peep: 'Peep', target_peep_id: str, delta: float) -> float:
    """Add *delta* to *source_peep*'s baseline vibe toward *target_peep_id*.

    Returns the new (unclamped) score.
    """
    current = get_baseline(source_peep, target_peep_id)
    new_score = current + delta
    set_baseline(source_peep, target_peep_id, new_score)
    return new_score


def describe_vibe(v: float) -> str:
    """Return a human-readable descriptor for the vibe score *v*.

    Returns an empty string for a score of 0 (unknown).
    """
    v = float(v)
    if abs(v) <= _ZERO_EPSILON:
        return ""
    clamped = clamp_visible(v)
    if clamped > 0:
        for lo, hi, label in _POSITIVE_BANDS:
            if lo <= clamped <= hi:
                return label
        return "Friend 🙂"  # fallback for values between 0 and 1
    else:
        for lo, hi, label in _NEGATIVE_BANDS:
            if lo <= clamped <= hi:
                return label
        return "Annoyance 🙄"  # fallback


# ---------------------------------------------------------------------------
# Runtime API
# ---------------------------------------------------------------------------

def get_target_vibe(
    source_peep: 'Peep',
    target_peep: 'Peep',
    room: 'Room | None' = None,
    world: 'World | None' = None,
) -> float:
    """Return the current vibe of *source_peep* toward *target_peep*.

    Currently returns the baseline score directly.  Additional runtime
    modifiers (room bonuses, item effects, etc.) can be injected here later.
    """
    return get_baseline(source_peep, target_peep.peep_id)


def get_room_vibe(target_peep: 'Peep', room: 'Room') -> float:
    """Return the average vibe all other peeps in *room* have toward *target_peep*.

    Excludes *target_peep* itself.  Returns 0.0 if no other peeps are present.
    """
    target_id = target_peep.peep_id
    scores: list[float] = []

    for peep in room.peeps.values():
        if peep.peep_id != target_id:
            scores.append(get_baseline(peep, target_id))

    for user_obj in room.users.values():
        if user_obj.peep.peep_id != target_id:
            scores.append(get_baseline(user_obj.peep, target_id))

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def decay_active_baselines(
    world: 'World',
    amount_per_minute: float = DEFAULT_DECAY_PER_MINUTE,
) -> None:
    """Decay all baseline vibes in *world.peeps* toward zero by *amount_per_minute*.

    Active peeps are all entries in ``world.peeps`` (NPCs + connected users).
    Entries that reach zero (within epsilon) are removed per the spec's
    "unknown" semantics.
    """
    for peep in list(world.peeps.values()):
        vibes: dict[str, float] = getattr(peep, 'vibes', None)
        if not vibes:
            continue
        to_remove: list[str] = []
        for target_id, score in list(vibes.items()):
            if score > 0:
                new_score = score - amount_per_minute
                if new_score <= _ZERO_EPSILON:
                    to_remove.append(target_id)
                else:
                    vibes[target_id] = new_score
            elif score < 0:
                new_score = score + amount_per_minute
                if new_score >= -_ZERO_EPSILON:
                    to_remove.append(target_id)
                else:
                    vibes[target_id] = new_score
        for target_id in to_remove:
            vibes.pop(target_id, None)
