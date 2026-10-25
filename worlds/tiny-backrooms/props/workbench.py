"""Picture-workbench behavior: open the fragment activity and teach the code.

World-authored. Assembly itself is visual (the picture-pieces activity); the
authoritative gate stays on the exit door's ordered recitation.
"""

from __future__ import annotations

HINTS = {
    "br": "Backrooms order: HOLLOW EYE, KNOTTED BELL, BRASS KEY, PAPER MOTH. The fourth quarter is carried by what hunts.",
    "ud": "Upside order: ASHEN STAR, PETAL MAW, IRON FANG, DROWNED BELL. The fourth quarter is carried by what hunts.",
    "op": "Abyss order: YAWNING SIGIL, SIXTEEN THROATS, BLACK TIDE, CROOKED CROWN. The fourth quarter is carried by what hunts.",
}


def _level_of(context) -> str:
    target = context.target
    instance_id = str(getattr(target, "instance_id", "") or "")
    for level in ("br", "ud", "op"):
        if f"-{level}" in f"-{instance_id}-":
            return level
    return "br"


def on_quick_action(context, event):
    if event.action != "study":
        return
    level = _level_of(context)
    owned = sum(1 for i in range(4) if context.has_card(f"tb-piece-{level}-{i}"))
    context.start_activity("picture-pieces", f"Restore the {level} photograph")
    if owned >= 4:
        context.feedback(f"You have all four quarters. {HINTS[level]} Feed them to the exit door in order.", "success")
    else:
        context.feedback(
            f"You hold {owned} of 4 quarters. {HINTS[level]} Search the level's props; one quarter is guarded.",
            "info",
        )
