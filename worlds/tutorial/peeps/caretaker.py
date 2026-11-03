"""Behavior hooks for the house's declarative tutorial guide."""

from __future__ import annotations

STINKY_LINE = "Whew, {name}! You smell like a compost bin that lost a fight. Shower first, hero."

HOUSE_TOUR_TASK_ID = "house-tour"
POOP_STEP_ID = "bag-poop"
POOP_CARD_ID = "poop-in-a-bag"
KEY_STEP_ID = "find-key"
KEY_CARD_ID = "house-key"
MULTIVERSE_MAP_CARD_ID = "multiverse-map"
SKIP_TUTORIAL_ACTION = "skip-tutorial"


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


def _skip_tutorial(context) -> None:
    if context.has_card(MULTIVERSE_MAP_CARD_ID):
        context.feedback(
            "You already have the Multiverse Map. Pip pats your pockets anyway, for closure.",
            "info",
        )
        return
    context.give_card(MULTIVERSE_MAP_CARD_ID)
    context.npc_say("Fine. Take the map. Try not to break causality; it's load-bearing.")
    context.feedback(
        "Pip skips the tutorial and hands over the Multiverse Map. The house looks relieved, or possibly offended.",
        "success",
    )


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
    """Catch up chore steps, or skip the tour and hand over the map."""

    if event.data.get("peep_id") != "caretaker":
        return
    if event.action == SKIP_TUTORIAL_ACTION:
        _skip_tutorial(context)
        return
    _complete_chores_if_holding(context)
