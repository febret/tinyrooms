"""Flavor-only hooks for Molly; the server owns activity and reward validation."""

from __future__ import annotations


def on_quick_action(context, event):
    """React to petting with flavor; defer play and dialog to the server."""

    if event.action == "pet":
        context.feedback("Molly leans into your hand and purrs like a tiny motor.")
