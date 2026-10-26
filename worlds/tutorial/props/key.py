"""Key-cabinet behavior: hands over the front-door key once it is safe."""

from __future__ import annotations


def on_quick_action(context, event):
    """Grant the house key when the cabinet is used and the bugs are gone."""

    if event.action not in {"take_key", "take", "use"}:
        return
    if context.prop_visible("bugs0"):
        context.feedback("Something is skittering around the cabinet. It has too many legs and not enough boundaries. Deal with it first.", "error")
        return
    if context.has_card("house-key"):
        context.feedback("You already have the key. It is in your inventory, being smug.")
        return
    context.give_card("house-key")
    context.update_task_progress("house-tour", "find-key")
    context.feedback("You pocket the brass sunflower key. It is warm, which is either comforting or deeply wrong.", "success")
