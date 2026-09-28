"""Litter-tray behavior: scooping poop, bagged or bare.

World-authored so the core server stays free of tutorial-specific card logic.
"""

from __future__ import annotations

SCOOPER_CARD_ID = "pooper-scooper"
BAG_CARD_ID = "plastic-bag"
OUTPUT_CARD_ID = "poop"
BAGGED_OUTPUT_CARD_ID = "poop-in-a-bag"


def on_card_play(context, event):
    """Resolve a pooper-scooper used on the litter tray."""

    if event.data.get("card_id") != SCOOPER_CARD_ID:
        return
    if context.has_equipped_card(BAG_CARD_ID):
        context.remove_card(BAG_CARD_ID, 1)
        context.give_card(BAGGED_OUTPUT_CARD_ID)
        context.feedback("You bagged up a poop in a bag.", "success")
        return
    context.give_card(OUTPUT_CARD_ID)
    context.set_counter("cleanliness", 0)
    context.feedback("You scooped up a piece of poop. Eww.", "success")
