"""Small behavior hooks for the house's declarative tutorial guide."""

from __future__ import annotations

STINKY_LINE = "Whew! Someone needs a shower before they track that through the house."


def _comment_if_stinky(context, event):
    if event.actor.kind == "user" and context.has_status("stinky"):
        context.npc_say(STINKY_LINE)


def on_enter(context, event):
    """Greet arrivals, and call out anyone who is stinky."""

    _comment_if_stinky(context, event)


def on_quick_action(context, event):
    """Open Pip's authored help tree through the validated dialog service."""

    if event.action in {"talk", "chat"}:
        if context.has_status("stinky"):
            context.npc_say(STINKY_LINE)
            return
        context.start_dialog("caretaker", "start")
