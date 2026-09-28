"""Centipede behavior: vacuuming the nest clears the basement's scare.

World-authored so the core server stays free of tutorial-specific card logic.
"""

from __future__ import annotations

VACUUM_CARD_ID = "vacuum-cleaner"
SCARY_SOURCE = "scary"
HIDE_SECONDS = 3600


def on_card_play(context, event):
    """Resolve a vacuum cleaner used on the centipedes."""

    if event.data.get("card_id") != VACUUM_CARD_ID:
        return
    context.hide_prop(HIDE_SECONDS)
    context.clear_source(SCARY_SOURCE)
    context.feedback("You clear the centipedes.", "success")
