"""Validation for the room editor environment allowlist."""

from __future__ import annotations

from typing import Any

from server.content.common import ContentError


EDITOR_ENVIRONMENT_KEYS = frozenset({"palette", "board_image_style", "board_image"})


def load_editor_environment(raw_value: Any, room_id: str) -> tuple[str, ...]:
    """Validate an authored room's editor environment keys."""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, dict):
        raise ContentError(f"Room '{room_id}' editor must be a mapping.")
    raw_keys = raw_value.get("environment", []) or []
    if not isinstance(raw_keys, list):
        raise ContentError(f"Room '{room_id}' editor.environment must be a list.")
    keys: list[str] = []
    for key in raw_keys:
        if not isinstance(key, str) or key not in EDITOR_ENVIRONMENT_KEYS:
            raise ContentError(
                f"Room '{room_id}' editor.environment has unknown key '{key}'. "
                f"Expected one of {', '.join(sorted(EDITOR_ENVIRONMENT_KEYS))}."
            )
        if key not in keys:
            keys.append(key)
    return tuple(keys)
