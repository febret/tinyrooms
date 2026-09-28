"""Flavor-only hooks for Molly; the server owns activity and reward validation."""

from __future__ import annotations

from datetime import datetime, timedelta
import random

STINKY_LINE = "Mrrrp, {name}! You smell like my litter tray. Go take a shower!"
MOVE_INTERVAL_SECONDS = 60
MOVE_CHANCE = 0.5


def _stinky_line(context) -> str:
    return STINKY_LINE.format(name=context.actor_name)


def _move_due(context) -> bool:
    """Return True at most once per interval, stamping the attempt time."""

    now = context.now
    previous = context.state.get("last_move_at")
    if isinstance(previous, str):
        try:
            previous_at = datetime.fromisoformat(previous)
        except ValueError:
            previous_at = None
    else:
        previous_at = None
    if previous_at is not None and (now - previous_at) < timedelta(seconds=MOVE_INTERVAL_SECONDS):
        return False
    context.state["last_move_at"] = now.isoformat()
    return True


def on_tick(context, event):
    """Wander the dollhouse: every minute, sometimes take a random exit."""

    if not _move_due(context):
        return
    if random.random() >= MOVE_CHANCE:
        return
    exits = [
        exit_definition
        for exit_definition in context.room.get("exits", [])
        if not exit_definition.get("npc_barrier") and not exit_definition.get("locked")
    ]
    if not exits:
        return
    context.move_through(random.choice(exits)["id"])


def _comment_if_stinky(context, event):
    if event.actor.kind == "user" and context.has_status("stinky"):
        context.npc_say(_stinky_line(context))


def on_enter(context, event):
    """Call out a stinky visitor the moment they arrive."""

    _comment_if_stinky(context, event)


def on_quick_action(context, event):
    """React to petting with flavor; defer play and dialog to the server."""

    if context.has_status("stinky") and event.action in {"pet", "talk", "chat"}:
        context.npc_say(_stinky_line(context))
        return
    if event.action == "pet":
        context.feedback("Molly leans into your hand and purrs like a tiny motor.")
