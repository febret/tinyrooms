"""Litter-tray behavior: scooping poop, bagged or bare.

World-authored so the core server stays free of tutorial-specific card logic.
"""

from __future__ import annotations

SCOOP_TAG = "scoop"
BARE_OUTPUT_CARD_ID = "poop"
BAGGED_OUTPUT_CARD_ID = "poop-in-a-bag"


def on_card_play(context, event):
    """Resolve a pooper-scooper used on the litter tray."""

    card = context.card
    if card is None or SCOOP_TAG not in card.tags:
        return
    if card.consume_card and context.has_equipped_card(card.consume_card):
        context.remove_card(card.consume_card, 1)
        context.give_card(BAGGED_OUTPUT_CARD_ID)
        context.feedback("You bagged up a poop in a bag.", "success")
        return
    context.give_card(BARE_OUTPUT_CARD_ID)
    context.set_counter("cleanliness", 0)
    context.feedback("You scooped up a piece of poop. Eww.", "success")
