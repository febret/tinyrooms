"""Built-in toilet behavior: restore a little Health and Cleanliness."""

from __future__ import annotations

import math

from server.behaviors.cooldown import mark_used, remaining_seconds

COOLDOWN_SECONDS = 600

ACTIONS = {"toilet", "use", "flush", "sit", "go"}

RESTORE_FRACTION = 0.10


def on_quick_action(context, event):
    """Relieve the acting peep, restoring a fraction of Health and Cleanliness."""

    if event.action not in ACTIONS:
        return
    remaining = remaining_seconds(context, COOLDOWN_SECONDS)
    if remaining > 0:
        minutes = int(remaining // 60)
        if minutes >= 1:
            wait_label = f"{minutes} more minute{'s' if minutes != 1 else ''}"
        else:
            wait_label = f"{int(math.ceil(remaining))} more seconds"
        context.feedback(f"The plumbing is still settling. Give it {wait_label}.", "error")
        return
    mark_used(context)
    max_health = context.counter("max_health", 50.0)
    max_cleanliness = context.counter("max_cleanliness", 100.0)
    context.apply_counter("health", RESTORE_FRACTION * max(0.0, max_health))
    context.apply_counter("cleanliness", RESTORE_FRACTION * max(0.0, max_cleanliness))
    context.feedback("You take a moment and feel a little better.", "success")
