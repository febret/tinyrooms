"""Built-in toilet behavior: restore a little Health and Cleanliness."""

from __future__ import annotations

from datetime import datetime, timedelta
import math

COOLDOWN_SECONDS = 600

ACTIONS = {"toilet", "use", "flush", "sit", "go"}

RESTORE_FRACTION = 0.10


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
    """Relieve the acting peep, restoring a fraction of Health and Cleanliness."""

    if event.action not in ACTIONS:
        return
    remaining = _remaining_seconds(context)
    if remaining > 0:
        minutes = int(remaining // 60)
        if minutes >= 1:
            wait_label = f"{minutes} more minute{'s' if minutes != 1 else ''}"
        else:
            wait_label = f"{int(math.ceil(remaining))} more seconds"
        context.feedback(f"The plumbing is still settling. Give it {wait_label}.", "error")
        return
    context.state["last_used_at"] = context.now.isoformat()
    max_health = context.counter("max_health", 50.0)
    max_cleanliness = context.counter("max_cleanliness", 100.0)
    context.apply_counter("health", RESTORE_FRACTION * max(0.0, max_health))
    context.apply_counter("cleanliness", RESTORE_FRACTION * max(0.0, max_cleanliness))
    context.feedback("You take a moment and feel a little better.", "success")
