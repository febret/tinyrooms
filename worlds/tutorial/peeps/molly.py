"""Flavor-only hooks for Molly; the server owns activity and reward validation."""

from __future__ import annotations

STINKY_LINE = "Mrrrp! You smell like my litter tray. Go take a shower!"


def _comment_if_stinky(context, event):
    if event.actor.kind == "user" and context.has_status("stinky"):
        context.npc_say(STINKY_LINE)


def on_enter(context, event):
    """Call out a stinky visitor the moment they arrive."""

    _comment_if_stinky(context, event)


def on_quick_action(context, event):
    """React to petting with flavor; defer play and dialog to the server."""

    if context.has_status("stinky") and event.action in {"pet", "talk", "chat"}:
        context.npc_say(STINKY_LINE)
        return
    if event.action == "pet":
        context.feedback("Molly leans into your hand and purrs like a tiny motor.")
