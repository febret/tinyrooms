"""Lurking-monster behavior: an ordinary prop that becomes the monster.

World-authored. Each level hides one monster inside an innocent prop with two
mesh states (``dormant`` / ``revealed``). Searching the wrong prop switches the
mesh through the ``set_prop_state`` intent, marks the victim with a dread buff
(source ``horror``), and starts a ~150-second duel. Victory needs the level
weapon equipped and used on the prop (``strike`` action or card play); expiry
plus any further confrontation drags the victim back to the Backrooms entrance
with zeroed counters.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DREAD_SECONDS = 150
BITE_SECONDS = 20
BITE_DAMAGE = 2

LURKERS = {
    "blue-girl-lurker": {"level": "br", "tag": "lullaby", "weapon": "lullaby-music-box",
                         "piece": "tb-piece-br-3", "mark": "tb-mark-br",
                         "task": "tb-escape-1", "meet": "meet-blue-girl", "slay": "slay-blue-girl",
                         "cutscene": "summon-blue-girl",
                         "line": "The exit sign goes dark. The dark stands up, wearing a blue dress."},
    "demogorgon-lurker": {"level": "ud", "tag": "iron", "weapon": "iron-bat",
                          "piece": "tb-piece-ud-3", "mark": "tb-mark-ud",
                          "task": "tb-escape-2", "meet": "meet-demogorgon", "slay": "slay-demogorgon",
                          "cutscene": "summon-demogorgon",
                          "line": "The nest unfolds. Petals of teeth open where the dark was."},
    "shoggoth-lurker": {"level": "op", "tag": "elder", "weapon": "elder-sign",
                        "piece": "tb-piece-op-3", "mark": "tb-mark-op",
                        "task": "tb-escape-3", "meet": "meet-shoggoth", "slay": "slay-shoggoth",
                        "cutscene": "summon-shoggoth",
                        "line": "The mound bubbles upward. It is coming to be introduced."},
}


def _lurker_of(context):
    target = context.target
    prop_id = str(getattr(target, "prop_id", "") or "")
    return prop_id, LURKERS.get(prop_id)


def _revealed(context) -> bool:
    return bool(context.state.get("revealed"))


def _throttled(context, key: str, seconds: int) -> bool:
    try:
        last = datetime.fromisoformat(str(context.state.get(key, "")))
    except (TypeError, ValueError):
        last = None
    if last is not None and context.now - last < timedelta(seconds=seconds):
        return False
    context.state[key] = context.now.isoformat()
    return True


def _doom(context, lurker: dict) -> None:
    context.remove_card(lurker["mark"], 1)
    context.clear_source("horror")
    context.set_counter("health", 0)
    context.set_counter("energy", 0)
    context.set_counter("cleanliness", 0)
    context.set_environment("lighting", None)
    context.set_prop_state("dormant")
    context.state["revealed"] = False
    context.cutscene("doom-dragged-back", audience="private")
    context.request_move("br-r0c0")
    context.room_feedback("The dark takes them. It always collects.", style="error")


def _victory(context, lurker: dict) -> None:
    context.remove_card(lurker["mark"], 1)
    context.clear_source("horror")
    context.set_environment("lighting", None)
    context.set_prop_state("dormant")
    context.state["revealed"] = False
    if not context.has_card(lurker["piece"]):
        context.give_card(lurker["piece"])
    context.grant(bops=25, ledger_key=f"tb-slew-{lurker['task']}")
    context.update_task_progress(lurker["task"], lurker["slay"])
    context.cutscene("monster-slain", audience="room")
    context.feedback("It recoils, folds, and is gone. The last photo quarter is yours.", "success")


def _resolve_strike(context, lurker: dict) -> None:
    if not _revealed(context):
        context.feedback("Nothing here but an ordinary prop. Search it if you are curious.", "info")
        return
    if not context.has_card(lurker["mark"]):
        context.feedback("It is hunting someone else. Do not volunteer.", "error")
        return
    if "scared" not in context.statuses:
        _doom(context, lurker)
        return
    if not context.has_equipped_card(lurker["weapon"]):
        context.apply_counter("health", -3)
        context.feedback(
            f"Wrong tool. You need the equipped {lurker['weapon'].replace('-', ' ')}. It notices you noticing.",
            "error",
        )
        return
    _victory(context, lurker)


def on_quick_action(context, event):
    _prop_id, lurker = _lurker_of(context)
    if lurker is None:
        return
    if event.action == "search":
        if _revealed(context):
            if context.has_card(lurker["mark"]) and "scared" not in context.statuses:
                _doom(context, lurker)
                return
            context.feedback("It is already hunting. Strike with the right tool.", "error")
            return
        if context.has_card(lurker["mark"]):
            context.feedback("It is already hunting you elsewhere. Finish that first.", "error")
            return
        context.state["revealed"] = True
        context.set_prop_state("revealed")
        context.give_card(lurker["mark"])
        context.apply_buff("dread", duration_seconds=DREAD_SECONDS, source="horror")
        try:
            context.set_environment("lighting", "dark")
        except Exception:  # noqa: BLE001 - flavor must not break the reveal
            pass
        context.cutscene(lurker["cutscene"], audience="room")
        context.update_task_progress(lurker["task"], lurker["meet"])
        context.room_feedback(lurker["line"], style="error")
        return
    if event.action == "strike":
        if context.has_card(lurker["mark"]) and "scared" not in context.statuses and _revealed(context):
            _doom(context, lurker)
            return
        _resolve_strike(context, lurker)


async def on_tick(context, event):
    _prop_id, lurker = _lurker_of(context)
    if lurker is None or not _revealed(context):
        return
    if context.room_users is None:
        return
    try:
        occupants = await context.room_users(event.room_id or "")
    except Exception:  # noqa: BLE001 - aura damage is flavor, never fatal to the tick
        return
    if not occupants:
        return
    if not _throttled(context, "last_bite_at", BITE_SECONDS):
        return
    from server.behaviors.events import PeepRef

    for entry in occupants:
        user_id = entry.get("id")
        if not user_id:
            continue
        context.apply_counter("health", -BITE_DAMAGE,
                              target=PeepRef(kind="user", peep_id=None, account_id=str(user_id)))
    context.room_feedback("The dark presses closer. Its patience is thinner than yours.", style="error")


def on_card_play(context, event):
    _prop_id, lurker = _lurker_of(context)
    if lurker is None or not _revealed(context):
        return
    card = context.card
    if card is None:
        return
    if lurker["tag"] in card.tags:
        if context.has_card(lurker["mark"]) and "scared" not in context.statuses:
            _doom(context, lurker)
            return
        _resolve_strike(context, lurker)
        return
    context.feedback("It shrugs that off. Only the right tool will turn it.", "error")
