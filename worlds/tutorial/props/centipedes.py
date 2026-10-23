"""Centipede behavior: vacuuming hides the nest for five minutes.

World-authored so the core server stays free of tutorial-specific card logic.
"""

from __future__ import annotations


def on_card_play(context, event):
    """Resolve a vacuum cleaner used on the centipedes."""

    card = context.card
    if card is None or "vacuum" not in card.tags:
        return
    context.hide_prop(300)
    context.feedback("You clear the centipedes. The basement feels emptier, and somehow more judgmental.", "success")
