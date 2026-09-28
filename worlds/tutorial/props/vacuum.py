"""Vacuum-stand behavior: lends the vacuum cleaner card once."""

from __future__ import annotations


def on_quick_action(context, event):
    """Grant the vacuum cleaner card when the prop is used."""

    if event.action not in {"take_vacuum", "borrow", "use"}:
        return
    if context.room_lighting() == "dark":
        context.feedback("It is too dark to find the vacuum.", "error")
        return
    if context.has_card("vacuum-cleaner"):
        context.feedback("You already have the vacuum cleaner.")
        return
    context.give_card("vacuum-cleaner")
    context.feedback("You borrow the vacuum cleaner.", "success")
