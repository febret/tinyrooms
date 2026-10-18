"""Trade bagged poop for a missing teleporter instruction manual."""

from __future__ import annotations

from server.behaviors.context import BehaviorContext
from server.behaviors.events import BehaviorEvent


def on_card_play(context: BehaviorContext, event: BehaviorEvent) -> None:
    """Dispose of a bag and provide the manual only when it is missing."""

    if context.card is None or context.card.id != "poop-in-a-bag":
        return
    if context.has_card("teleporter-instruction-manual"):
        context.feedback("You throw away the poop in a bag. You already have the teleporter instruction manual.", "success")
        return
    context.give_card("teleporter-instruction-manual")
    context.feedback("You throw away the poop in a bag and find a teleporter instruction manual!", "success")
