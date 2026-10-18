"""Key-cabinet behavior: hands over the front-door key once it is safe."""

from __future__ import annotations


def on_quick_action(context, event):
    """Grant the house key when the cabinet is used and the bugs are gone."""

    if event.action not in {"take_key", "take", "use"}:
        return
    if context.prop_visible("bugs0"):
        context.feedback("Something is skittering around the cabinet. Deal with it first.", "error")
        return
    if context.has_card("house-key"):
        context.feedback("You already have the key.")
        return
    context.give_card("house-key")
    context.feedback("You pocket the little brass key.", "success")
