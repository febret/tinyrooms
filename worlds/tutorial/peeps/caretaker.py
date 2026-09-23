"""Small behavior hooks for the house's declarative tutorial guide."""

from __future__ import annotations


def on_quick_action(context, event):
    """Open Pip's authored help tree through the validated dialog service."""

    if event.action in {"talk", "chat"}:
        context.start_dialog("caretaker", "start")
