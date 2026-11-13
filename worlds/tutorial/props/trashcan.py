"""Garden trashcan accepts bagged poop."""

from __future__ import annotations

from server.behaviors.context import BehaviorContext
from server.behaviors.events import BehaviorEvent

GARDEN_ROOM_ID = "garden"


def on_card_play(context: BehaviorContext, event: BehaviorEvent) -> None:
    """Dispose of a bagged poop in the garden."""

    if context.card is None or context.card.id != "poop-in-a-bag":
        return
    if event.room_id != GARDEN_ROOM_ID:
        return
    context.feedback(
        "You throw away the poop in a bag. The trashcan accepts your offering.",
        "success",
    )
