"""Flavor-only hooks for Molly; the server owns activity and reward validation."""


def on_action(context, action, **kwargs):
    """Handle petting as flavor only; defer play and dialog to the server."""
    if action == "pet":
        text = "Molly leans into your hand and purrs like a tiny motor."
        context.emit("npc", text, peep="molly")
        return text
    return None
