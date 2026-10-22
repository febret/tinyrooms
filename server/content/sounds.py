"""Validation helpers for authored sound references."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from server.content.common import ContentError


SOUND_FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.wav$")
PROP_SOUND_KEYS = frozenset({"select", "action"})
CARD_SOUND_KEYS = frozenset({"select", "use"})
CUTSCENE_SOUND_KEYS = frozenset({"start"})
TASK_SOUND_KEYS = frozenset({"started", "completed", "notification"})


def load_sound_names(root: Path) -> frozenset[str]:
    """Return the available sound file names beneath *root*."""

    if not root.is_dir():
        return frozenset()
    return frozenset(path.name for path in root.glob("*.wav") if path.is_file())


def validate_sound_name(value: Any, label: str, known_sounds: frozenset[str] | None = None) -> str:
    """Return a validated sound file name."""

    name = str(value or "").strip()
    if not SOUND_FILE_PATTERN.match(name):
        raise ContentError(f"{label} must be a .wav file name without a path.")
    if known_sounds is not None and name not in known_sounds:
        raise ContentError(f"{label} references missing sound '{name}'.")
    return name


def parse_sounds(
    raw_value: Any,
    label: str,
    allowed_keys: frozenset[str],
    *,
    known_sounds: frozenset[str] | None = None,
) -> dict[str, str]:
    """Parse an authored ``sounds`` mapping with a fixed set of keys."""

    if raw_value is None:
        return {}
    if not isinstance(raw_value, Mapping):
        raise ContentError(f"{label} sounds must be a mapping.")
    sounds: dict[str, str] = {}
    for raw_key, raw_name in raw_value.items():
        key = str(raw_key).strip().lower()
        if key not in allowed_keys:
            raise ContentError(
                f"{label} has unknown sound key '{raw_key}'. "
                f"Expected one of {', '.join(sorted(allowed_keys))}."
            )
        if key in sounds:
            raise ContentError(f"{label} repeats sound key '{key}'.")
        sounds[key] = validate_sound_name(
            raw_name,
            f"{label} sound '{key}'",
            known_sounds,
        )
    return sounds


def parse_sound(value: Any, label: str, known_sounds: frozenset[str] | None = None) -> str | None:
    """Parse an optional single sound reference."""

    if value is None:
        return None
    name = str(value).strip()
    if not name:
        return None
    return validate_sound_name(name, label, known_sounds)


def sound_url(name: str) -> str:
    """Return the served URL for a validated sound name."""

    return f"/assets/sounds/{name}"


def sounds_payload(sounds: Mapping[str, str]) -> dict[str, str]:
    """Serialize authored sounds as served URLs."""

    return {key: sound_url(name) for key, name in sorted(sounds.items())}
