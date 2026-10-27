"""Built-in washing-station behavior: restore Cleanliness with a short cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta
import math

COOLDOWN_SECONDS = 120

ACTIONS = {"wash", "use", "bathe", "shower", "clean", "swim", "dip", "soak", "rinse"}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _remaining_seconds(context) -> float:
    last_used = _parse_timestamp(context.state.get("last_used_at"))
    if last_used is None:
        return 0.0
    if last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=context.now.tzinfo)
    remaining = (last_used + timedelta(seconds=COOLDOWN_SECONDS) - context.now).total_seconds()
    return max(0.0, remaining)


def on_quick_action(context, event):
    """Scrub the acting peep clean unless the station is still recharging."""

    if event.action not in ACTIONS:
        return
    if context.has_equipped_card("poop"):
        context.feedback("Put that poop away before you wash up. The basin has seen enough.", "error")
        return
    remaining = _remaining_seconds(context)
    if remaining > 0:
        context.feedback(
            f"The basin is still dripping. Give it {int(math.ceil(remaining))} more seconds.",
            "error",
        )
        return
    context.state["last_used_at"] = context.now.isoformat()
    context.set_counter("cleanliness", context.counter("max_cleanliness", 100.0))
    context.clear_decals(kind="paint")
    context.feedback("You wash up and feel squeaky clean.", "success")
