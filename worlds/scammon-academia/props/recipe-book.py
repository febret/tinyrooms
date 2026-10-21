"""Supermarket recipe-book behavior: reading unlocks the cardset's recipes."""

from __future__ import annotations

SUPERMARKET_SOURCE = "supermarket"


def on_quick_action(context, event):
    """Teach every supermarket recipe to the reader."""

    if event.action not in {"read", "study", "use"}:
        return
    context.learn_recipes(source=SUPERMARKET_SOURCE)
