"""Shower behavior: restores Cleanliness unless a poop card is equipped."""

from __future__ import annotations


def on_quick_action(context, event):
    """Run the shower when its quick action is invoked."""

    if event.action not in {"shower", "use"}:
        return
    if context.room_lighting() == "dark":
        context.feedback("It is too dark to find the shower.", "error")
        return
    if context.has_status("scared"):
        context.feedback("You are too scared to step into the shower.", "error")
        return
    if context.has_equipped_card("poop"):
        context.feedback("Put that poop away before you step into the shower.", "error")
        return
    context.set_counter("cleanliness", context.counter("max_cleanliness", 100.0))
    context.feedback("You take a warm shower and feel squeaky clean.", "success")
