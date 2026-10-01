"""Centipede behavior: vacuuming the nest clears the basement's scare.

World-authored so the core server stays free of tutorial-specific card logic.
"""

from __future__ import annotations


def on_card_play(context, event):
    """Resolve a vacuum cleaner used on the centipedes."""

    card = context.card
    if card is None or "vacuum" not in card.tags:
        return
    if card.hide_seconds is not None:
        context.hide_prop(float(card.hide_seconds))
    if card.clears_source:
        context.clear_source(card.clears_source)
    context.feedback("You clear the centipedes.", "success")
