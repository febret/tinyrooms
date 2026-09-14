"""Small behavior hooks for the house's declarative tutorial guide."""


def on_action(context, action, **kwargs):
    """Open Pip's authored help tree through the server's dialog validator."""
    if action in {"talk", "chat"}:
        peep = context.world["peeps"]["caretaker"]
        return context.engine.dispatcher.start_dialog(context, "caretaker", peep, "start")
    return None
