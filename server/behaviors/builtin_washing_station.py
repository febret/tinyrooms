"""Built-in washing-station behavior: restore Cleanliness with a short cooldown."""

from __future__ import annotations

import math

from server.behaviors.cooldown import mark_used, remaining_seconds

COOLDOWN_SECONDS = 120

ACTIONS = {"wash", "use", "bathe", "shower", "clean", "swim", "dip", "soak", "rinse"}


def on_quick_action(context, event):
    """Scrub the acting peep clean unless the station is still recharging."""

    if event.action not in ACTIONS:
        return
    if context.has_equipped_card("poop"):
        context.feedback("Put that poop away before you wash up. The basin has seen enough.", "error")
        return
    remaining = remaining_seconds(context, COOLDOWN_SECONDS)
    if remaining > 0:
        context.feedback(
            f"The basin is still dripping. Give it {int(math.ceil(remaining))} more seconds.",
            "error",
        )
        return
    mark_used(context)
    context.set_counter("cleanliness", context.counter("max_cleanliness", 100.0))
    context.clear_decals(kind="paint")
    context.feedback("You wash up and feel squeaky clean.", "success")
