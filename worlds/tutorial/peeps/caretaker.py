"""Small behavior hooks for the house's declarative tutorial guide."""

from __future__ import annotations

STINKY_LINE = "Whew, {name}! Someone needs a shower before they track that through the house."


def _stinky_line(context) -> str:
    return STINKY_LINE.format(name=context.actor_name)


def _comment_if_stinky(context, event):
    if event.actor.kind == "user" and context.has_status("stinky"):
        context.npc_say(_stinky_line(context))


def on_enter(context, event):
    """Greet arrivals, and call out anyone who is stinky."""

    _comment_if_stinky(context, event)


def on_quick_action(context, event):
    """Open Pip's authored help tree through the validated dialog service."""

    if event.action in {"talk", "chat"}:
        if context.has_status("stinky"):
            context.npc_say(_stinky_line(context))
            return
        context.start_dialog("caretaker", "start")
