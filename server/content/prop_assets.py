"""Prop model placeholder and served-URL helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


PROP_MODEL_PLACEHOLDER_PATH = (
    Path(__file__).resolve().parents[2] / "client" / "app" / "assets" / "missing-prop.glb"
)
PROP_MODEL_PLACEHOLDER_URL = "/app/assets/missing-prop.glb"


def _prop_model_state(definition: Any, state: str | None) -> Any | None:
    if not state:
        return None
    states = getattr(definition, "states", {}) or {}
    return states.get(state)


def prop_model_url(
    world_id: str,
    definition: Any,
    state: str | None = None,
) -> str | None:
    """Return the served URL for a prop model from a world, propset, or mod."""

    if getattr(definition, "render_kind", "model") != "model":
        return None
    state_definition = _prop_model_state(definition, state)
    if state_definition is not None:
        if getattr(state_definition, "model_missing", False):
            return PROP_MODEL_PLACEHOLDER_URL
        model_name: str | None = state_definition.model_name
    else:
        if getattr(definition, "model_missing", False):
            return PROP_MODEL_PLACEHOLDER_URL
        model_name = definition.model_name
    if definition.source_kind == "mod":
        return f"/assets/mods/{definition.source}/props/{model_name}"
    if definition.source_kind == "propset":
        return f"/assets/propsets/{definition.source}/{model_name}"
    return f"/assets/world/{world_id}/props/{model_name}"
