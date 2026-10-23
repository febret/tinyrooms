"""Trade bagged poop for the Multiverse Map in the garden."""

from __future__ import annotations

from server.behaviors.context import BehaviorContext
from server.behaviors.events import BehaviorEvent

GARDEN_ROOM_ID = "garden"
MULTIVERSE_MAP_CARD_ID = "multiverse-map"
MAP_FOUND_CUTSCENE_ID = "multiverse-map-found"


def on_card_play(context: BehaviorContext, event: BehaviorEvent) -> None:
    """Dispose of a bag and provide the Multiverse Map only when it is missing."""

    if context.card is None or context.card.id != "poop-in-a-bag":
        return
    if event.room_id != GARDEN_ROOM_ID:
        return
    if context.has_card(MULTIVERSE_MAP_CARD_ID):
        context.feedback(
            "You throw away the poop in a bag. The trashcan accepts your offering. You already have the Multiverse Map; the universe is being stingy today.",
            "success",
        )
        return
    context.give_card(MULTIVERSE_MAP_CARD_ID)
    context.cutscene(MAP_FOUND_CUTSCENE_ID)
    context.feedback(
        "You throw away the poop in a bag and find the Multiverse Map! The trashcan is either magical or very bad at its job.",
        "success",
    )
