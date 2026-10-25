"""Exit-door behavior: feed photo pieces to the door in code order.

World-authored. The door tracks shared recitation progress in its instance
state; the restored photograph it grants is per-player and opens the linked
exit through the native ``requires`` gate.
"""

from __future__ import annotations

DOORS = {
    "exit-door-br": {"level": "br", "task": "tb-escape-1", "step": "open-br-door",
                     "code": ["tb-piece-br-0", "tb-piece-br-1", "tb-piece-br-2", "tb-piece-br-3"],
                     "restored": "tb-restored-br",
                     "hint": "HOLLOW EYE, KNOTTED BELL, BRASS KEY, PAPER MOTH"},
    "exit-door-ud": {"level": "ud", "task": "tb-escape-2", "step": "open-ud-door",
                     "code": ["tb-piece-ud-0", "tb-piece-ud-1", "tb-piece-ud-2", "tb-piece-ud-3"],
                     "restored": "tb-restored-ud",
                     "hint": "ASHEN STAR, PETAL MAW, IRON FANG, DROWNED BELL"},
    "exit-door-op": {"level": "op", "task": "tb-escape-3", "step": "open-op-door",
                     "code": ["tb-piece-op-0", "tb-piece-op-1", "tb-piece-op-2", "tb-piece-op-3"],
                     "restored": "tb-restored-op",
                     "hint": "YAWNING SIGIL, SIXTEEN THROATS, BLACK TIDE, CROOKED CROWN"},
}


def _door_of(context):
    target = context.target
    prop_id = getattr(target, "prop_id", "") if target is not None else ""
    return DOORS.get(str(prop_id))


def _progress(context) -> int:
    try:
        return int(context.state.get("pos", 0))
    except (TypeError, ValueError):
        return 0


def on_quick_action(context, event):
    if event.action != "study":
        return
    door = _door_of(context)
    if door is None:
        return
    if context.has_card(door["restored"]):
        context.feedback("The door stands open for you. The sockets are dark; the code is spent.", "success")
        return
    pos = _progress(context)
    context.feedback(
        f"Four sockets in a row, {pos} of 4 lit. Use the photo pieces on the door in order: {door['hint']}.",
        "info",
    )


def on_card_play(context, event):
    door = _door_of(context)
    if door is None:
        return
    card = context.card
    if card is None or "code" not in card.tags:
        return
    if context.has_card(door["restored"]):
        context.feedback("The door already opened for you once. It remembers.", "info")
        return
    pos = _progress(context)
    expected = door["code"][pos] if pos < len(door["code"]) else None
    if card.id == expected:
        pos += 1
        context.state["pos"] = pos
        if pos >= len(door["code"]):
            context.state["pos"] = 0
            context.give_card(door["restored"])
            context.update_task_progress(door["task"], door["step"])
            context.cutscene("door-unlocks", audience="room")
            context.room_feedback("The exit door drinks the symbols and swings open.", style="success")
        else:
            context.feedback(f"The socket flares and holds ({pos} of 4). Keep going, in order.", "success")
        return
    context.state["pos"] = 0
    context.feedback("The sockets gutter out. Wrong order; the door resets. Study it, then begin again.", "error")
