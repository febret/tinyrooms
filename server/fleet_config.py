"""Shared parsing for fleet content files (``multiworld.json``).

The local launcher (``start_multiworld.py``) and the deployment packager
(``tools/deploy_content.py``) read the same world entries; entry-level
validation lives here so the two can never disagree about which worlds a
fleet file selects.
"""

from __future__ import annotations

import re
from typing import Any


_WORLD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def entry_enabled(entry: Any, index: int, *, error: type[ValueError] = ValueError) -> bool:
    """Return whether one fleet entry is enabled (plain ids are always enabled)."""

    if not isinstance(entry, dict):
        return True
    value = entry.get("enabled", True)
    if not isinstance(value, bool):
        raise error(f"worlds[{index}].enabled must be a boolean.")
    return value


def entry_world_id(entry: Any, index: int, *, error: type[ValueError] = ValueError) -> str:
    """Return the validated world id for one fleet entry."""

    if isinstance(entry, str):
        world_id = entry.strip()
    elif isinstance(entry, dict):
        raw = entry.get("id", entry.get("world"))
        if not isinstance(raw, str):
            raise error(f"worlds[{index}] must have a string 'id'.")
        world_id = raw.strip()
    else:
        raise error(f"worlds[{index}] must be a world id or an object.")
    if not _WORLD_ID_PATTERN.match(world_id):
        raise error(f"worlds[{index}] has an invalid world id '{world_id}'.")
    return world_id


def entry_path(
    entry: Any,
    index: int,
    key: str,
    *,
    error: type[ValueError] = ValueError,
) -> str | None:
    """Return the optional stripped path stored under *key*, or None."""

    if not isinstance(entry, dict):
        return None
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise error(f"worlds[{index}].{key} must be a non-empty path string.")
    return value.strip()
