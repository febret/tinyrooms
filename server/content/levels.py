"""Level-based equipment limits loaded from core content."""

from __future__ import annotations

from pathlib import Path

from server.content.common import ContentError, load_yaml_file, require_mapping

DEFAULT_MAX_EQUIPPED = 5


def load_equipped_caps(core_path: Path) -> dict[int, int]:
    """Load per-level equipped-card caps from levels.yaml."""

    path = core_path / "levels.yaml"
    payload = require_mapping(load_yaml_file(path), path)
    caps: dict[int, int] = {}
    for raw_level, raw_entry in payload.items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError) as exc:
            raise ContentError(f"{path} has an invalid level '{raw_level}'.") from exc
        if not isinstance(raw_entry, dict):
            raise ContentError(f"{path} level {level} must define a mapping.")
        raw_cap = raw_entry.get("max_equipped", DEFAULT_MAX_EQUIPPED)
        if isinstance(raw_cap, bool) or not isinstance(raw_cap, int):
            raise ContentError(f"{path} level {level} has an invalid max_equipped {raw_cap!r}.")
        cap = raw_cap
        if level < 0 or cap < 0:
            raise ContentError(f"{path} level {level} has an invalid max_equipped {cap}.")
        caps[level] = cap
    if not caps:
        raise ContentError(f"{path} must define at least one level.")
    return caps
