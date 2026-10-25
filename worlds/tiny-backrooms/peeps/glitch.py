"""Glitch-creature behavior: hostile peeps debugged with the deglitcher.

World-authored. Glitches bite visitors and pokers, and collapse into loot when
zapped with an equipped deglitcher. Defeat is per-peep with a slow re-glitch so
latecomers still meet a live pest.
"""

from __future__ import annotations

from datetime import datetime, timedelta

GLITCHES = {
    "glitch-rat": {"loot": "fluorescent-tube", "taunt": "The rat stutters sideways through the floor. It bites in keyframes."},
    "glitch-spider": {"loot": "portal-jerky", "taunt": "The spider renders leg-first. Too many legs. All of them angry."},
    "glitch-monkey": {"loot": "demodog-tooth", "taunt": "The monkey screeches in compressed audio. It throws a corrupted barrel."},
    "glitch-bat": {"loot": "static-candy", "taunt": "The bat flickers through the wall and back, screaming static."},
    "glitch-worm": {"loot": "ectoplasm-vial", "taunt": "The worm segments desync. Each half bites independently. Rude."},
    "glitch-hound": {"loot": "black-seashell", "taunt": "The hound buffers mid-lunge, then arrives all at once."},
}

REGLITCH_SECONDS = 300


def _self_id(context, event) -> str | None:
    target = context.target
    peep_id = getattr(target, "peep_id", None) if target is not None else None
    if isinstance(peep_id, str) and peep_id in GLITCHES:
        return peep_id
    return None


def _defeated(context) -> bool:
    try:
        at = datetime.fromisoformat(str(context.state.get("defeated_at", "")))
    except (TypeError, ValueError):
        return False
    return context.now - at < timedelta(seconds=REGLITCH_SECONDS)


def on_enter(context, event):
    monster_id = _self_id(context, event)
    if monster_id is None:
        return
    actor = getattr(event, "actor", None)
    if actor is None or getattr(actor, "kind", "") != "user":
        return
    if _defeated(context):
        return
    context.apply_counter("health", -2)
    context.peep_say(monster_id, GLITCHES[monster_id]["taunt"])


def on_quick_action(context, event):
    monster_id = _self_id(context, event)
    if monster_id is None or event.action not in {"poke", "scan"}:
        return
    if _defeated(context):
        context.feedback("Debugged already. It twitches harmlessly, defragging.", "info")
        return
    if event.action == "scan":
        context.feedback("Scan: hostile glitch construct. Weakness: an equipped deglitcher, used on it.", "info")
        return
    context.apply_counter("health", -3)
    context.peep_say(monster_id, "It bites your cursor! Zap it with a deglitcher instead of your hands.")


def on_card_play(context, event):
    monster_id = _self_id(context, event)
    if monster_id is None:
        return
    card = context.card
    if card is None or "deglitch" not in card.tags:
        return
    if _defeated(context):
        context.feedback("Already debugged. Save the charge.", "info")
        return
    if not context.has_equipped_card(card.id):
        context.feedback("Equip the deglitcher first, then zap the glitch.", "error")
        return
    context.state["defeated_at"] = context.now.isoformat()
    loot = GLITCHES[monster_id]["loot"]
    if not context.has_card(loot):
        context.give_card(loot)
    context.grant(bops=5, ledger_key=f"tb-debug-{monster_id}-{context.now.date().isoformat()}")
    context.room_feedback("The glitch collapses into loot with a satisfied dial-up scream.", style="success")
