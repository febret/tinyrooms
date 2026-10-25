"""Small behavior hooks for the house's declarative tutorial guide."""

from __future__ import annotations

STINKY_LINE = "Whew, {name}! You smell like a compost bin that lost a fight. Shower first, hero."

HOUSE_TOUR_TASK_ID = "house-tour"
POOP_STEP_ID = "bag-poop"
POOP_CARD_ID = "poop-in-a-bag"
KEY_STEP_ID = "find-key"
KEY_CARD_ID = "house-key"


def _stinky_line(context) -> str:
    return STINKY_LINE.format(name=context.actor_name)


def _complete_chores_if_holding(context) -> None:
    """Complete poop/key steps immediately when the player already holds them.

    Uses explicit step advances so the task row is created on demand and the
    shared task reward (kudos + card) is granted idempotently on final
    completion, even when the task is unlocked after the items were earned.
    """

    if context.has_card(POOP_CARD_ID):
        context.update_task_progress(HOUSE_TOUR_TASK_ID, POOP_STEP_ID)
    if context.has_card(KEY_CARD_ID):
        context.update_task_progress(HOUSE_TOUR_TASK_ID, KEY_STEP_ID)


def _comment_if_stinky(context, event):
    if event.actor.kind == "user" and context.has_status("stinky"):
        context.npc_say(_stinky_line(context))


def on_enter(context, event):
    """Greet arrivals, and call out anyone who is stinky."""

    _comment_if_stinky(context, event)


def on_quick_action(context, event):
    """Open Pip's authored help tree through the validated dialog service."""

    if event.action in {"talk", "chat"}:
        _complete_chores_if_holding(context)
        if context.has_status("stinky"):
            context.npc_say(_stinky_line(context))
            return
        context.start_dialog("caretaker", "start")


def on_dialog_action(context, event):
    """Catch up chore steps when Pip's dialog runs with items already earned."""

    if event.data.get("peep_id") != "caretaker":
        return
    _complete_chores_if_holding(context)
