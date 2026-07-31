"""Core gameplay mechanics for tinyrooms.

Covers: User Level, Juice, Bops, and Kudos calculations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Level table  (L0–L10)
# ---------------------------------------------------------------------------

LEVEL_TABLE: list[dict[str, Any]] = [
    {"level": 0, "title": "Guest",          "icon": "",   "kudos_required": 0},
    {"level": 1, "title": "Novice",         "icon": "🔰", "kudos_required": 10},
    {"level": 2, "title": "Student",        "icon": "🌱", "kudos_required": 20},
    {"level": 3, "title": "Senior Student", "icon": "⚡", "kudos_required": 30},
    {"level": 4, "title": "Candidate",      "icon": "💧", "kudos_required": 40},
    {"level": 5, "title": "Acolyte",        "icon": "🟦", "kudos_required": 50},
    {"level": 6, "title": "White Scholar",  "icon": "🦭", "kudos_required": 60},
    {"level": 7, "title": "Green Scholar",  "icon": "🐢", "kudos_required": 70},
    {"level": 8, "title": "Red Scholar",    "icon": "🐙", "kudos_required": 80},
    {"level": 9, "title": "Master",         "icon": "⬛", "kudos_required": 90},
    {"level": 10, "title": "Grandmaster",   "icon": "🔳", "kudos_required": 100},
]

MAX_LEVEL = LEVEL_TABLE[-1]["level"]


def compute_level(total_kudos_received: int) -> dict[str, Any]:
    """Compute the level info for a user with the given total kudos received.

    Returns a dict with:
        level, title, icon, kudos_required, next_threshold
    ``next_threshold`` is None at max level.
    """
    current = LEVEL_TABLE[0]
    for entry in LEVEL_TABLE:
        if total_kudos_received >= entry["kudos_required"]:
            current = entry
        else:
            break
    level = current["level"]
    next_threshold: int | None = None
    if level < MAX_LEVEL:
        next_threshold = LEVEL_TABLE[level + 1]["kudos_required"]
    return {
        "level": level,
        "title": current["title"],
        "icon": current["icon"],
        "kudos_required": current["kudos_required"],
        "next_threshold": next_threshold,
    }


# ---------------------------------------------------------------------------
# Juice
# ---------------------------------------------------------------------------

BASE_MAX_JUICE: float = 100.0
JUICE_PER_LEVEL: float = 20.0

BASE_JUICE_RATE: float = 5.0   # juice per minute
JUICE_RATE_PER_LEVEL: float = 0.5

JUICE_COST_PER_MESSAGE: float = 1.0


def max_juice(level: int) -> float:
    """Maximum juice for the given level."""
    return BASE_MAX_JUICE + level * JUICE_PER_LEVEL


def base_juice_rate(level: int) -> float:
    """Base juice recharge rate (per minute) for the given level."""
    return BASE_JUICE_RATE + level * JUICE_RATE_PER_LEVEL


def juice_rate_for_user(user_obj: Any) -> float:
    """Effective juice recharge rate for *user_obj* accounting for trait modifiers."""
    from . import traits as traits_module
    level = getattr(user_obj, "level", 0)
    user_traits: list[str] = getattr(user_obj, "traits", []) or []
    rate = base_juice_rate(level)
    modifier = traits_module.get_juice_rate_modifier(user_traits)
    return rate * modifier


def juice_cost_per_message() -> float:
    """Juice cost incurred for each socket message sent by a user."""
    return JUICE_COST_PER_MESSAGE


def compute_juice_recovery(juice_last_tick_iso: str, rate: float) -> float:
    """Compute how much juice has recovered since *juice_last_tick_iso*.

    *rate* is in juice-per-minute.  Returns the (non-negative) amount recovered.
    """
    try:
        last = datetime.fromisoformat(juice_last_tick_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    now = datetime.now(timezone.utc)
    elapsed_minutes = max(0.0, (now - last).total_seconds() / 60.0)
    return elapsed_minutes * rate


# ---------------------------------------------------------------------------
# Bops
# ---------------------------------------------------------------------------

BASE_DAILY_BOPS: int = 10
BOPS_PER_LEVEL: int = 5


def daily_bops(level: int) -> int:
    """Bops awarded to a user each day based on their level."""
    return BASE_DAILY_BOPS + level * BOPS_PER_LEVEL


# ---------------------------------------------------------------------------
# Kudos
# ---------------------------------------------------------------------------

from . import user_data as _user_data  # noqa: E402  (avoids circular at module level)


def daily_kudos_budget() -> int:
    """How many kudos a user may give per day (global constant)."""
    return _user_data.DAILY_KUDOS_BUDGET


# ---------------------------------------------------------------------------
# Juice packs (purchasable with Bops)
# ---------------------------------------------------------------------------

JUICE_PACKS: dict[str, dict[str, int]] = {
    "small":  {"bops_cost": 5,  "juice_amount": 20},
    "medium": {"bops_cost": 15, "juice_amount": 60},
    "large":  {"bops_cost": 35, "juice_amount": 150},
}
