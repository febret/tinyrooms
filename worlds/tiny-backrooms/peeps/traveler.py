"""Traveler behavior: greeters who explain the level and hand out key intel.

World-authored. The heavy hint text lives in peeps.yaml dialog trees; this
script adds arrival greetings so each level teaches its monster, code order,
hazards, and gear without any core changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

GREETINGS = {
    "traveler-br": "Another live one! I am Mara. Listen fast: the door eats photo pieces in order, and something here eats travelers.",
    "traveler-ud": "You made it through. I am Jonathan. The vines took my town; do not let them take your picture.",
    "traveler-op": "Still sane? Good, that means early. I am the Cartographer. The abyss keeps the last door, and the last door keeps count.",
}

LAST_KEY = "last_greet_at"
GREET_SECONDS = 120


def on_enter(context, event):
    actor = getattr(event, "actor", None)
    if actor is None or getattr(actor, "kind", "") != "user":
        return
    data = getattr(event, "data", {}) or {}
    peep_id = data.get("peep_id")
    target = context.target
    if peep_id is None and target is not None:
        peep_id = getattr(target, "peep_id", None)
    greeting = GREETINGS.get(str(peep_id or ""))
    if greeting is None:
        return
    try:
        last = datetime.fromisoformat(str(context.state.get(LAST_KEY, "")))
    except (TypeError, ValueError):
        last = None
    if last is not None and context.now - last < timedelta(seconds=GREET_SECONDS):
        return
    context.state[LAST_KEY] = context.now.isoformat()
    context.npc_say(greeting)


def on_quick_action(context, event):
    if event.action not in {"chat", "talk", "greet"}:
        return
    target = context.target
    peep_id = str(getattr(target, "peep_id", "") or "")
    if peep_id in GREETINGS:
        context.start_dialog(peep_id, "start")
