"""Front-door behavior: stepping outside ends the tutorial.

World-authored so the core server stays free of tutorial-specific logic.
"""

from __future__ import annotations

GARDEN_ROOM_ID = "garden"
END_CUTSCENE_ID = "tutorial-end"


def on_leave(context, event):
    """Trash carried mess and congratulate the player on their first exit."""

    if event.data.get("destination_room_id") != GARDEN_ROOM_ID:
        return
    context.remove_card("poop")
    context.remove_card("poop-in-a-bag")
    account_id = event.actor.account_id
    if not account_id:
        return
    completed = context.state.setdefault("completed", [])
    if account_id in completed:
        return
    completed.append(account_id)
    context.cutscene(END_CUTSCENE_ID)
