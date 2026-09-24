"""Strict loader for activity launch definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from server.content.common import ContentError, load_yaml_file, require_mapping


@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    """An authored activity that commands can launch."""

    id: str
    title: str
    room_bound: bool
    aliases: tuple[str, ...]
    rooms: tuple[str, ...]
    required_feature: str | None
    source: str
    start_cost: int = 0
    record: bool = False
    min_completed_round: float = 0.0


def _load_string_list(raw_value: Any, label: str, path: Path) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError(f"{label} must be a list in {path}.")
    values: list[str] = []
    for value in raw_value:
        if not isinstance(value, str) or not value.strip():
            raise ContentError(f"{label} entries must be non-empty strings in {path}.")
        values.append(value.strip())
    return tuple(values)


def load_activity_definitions(
    path: Path,
    *,
    source: str,
    known_rooms: frozenset[str] = frozenset(),
    known_features: frozenset[str] = frozenset(),
) -> dict[str, ActivityDefinition]:
    """Load and validate activity definitions from a YAML file."""

    if not path.is_file():
        return {}
    payload = require_mapping(load_yaml_file(path), path)
    definitions: dict[str, ActivityDefinition] = {}
    for activity_id, raw in payload.items():
        if not isinstance(activity_id, str) or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid activity entry.")
        title = str(raw.get("title", "")).strip()
        if not title:
            raise ContentError(f"Activity '{activity_id}' must define a title.")
        room_bound = raw.get("room_bound", True)
        if not isinstance(room_bound, bool):
            raise ContentError(f"Activity '{activity_id}' room_bound must be a boolean.")
        aliases = _load_string_list(raw.get("aliases"), f"Activity '{activity_id}' aliases", path)
        rooms = _load_string_list(raw.get("rooms"), f"Activity '{activity_id}' rooms", path)
        for room_id in rooms:
            if known_rooms and room_id not in known_rooms:
                raise ContentError(f"Activity '{activity_id}' references unknown room '{room_id}'.")
        required_feature = raw.get("feature")
        if required_feature is not None:
            required_feature = str(required_feature).strip()
            if not required_feature:
                raise ContentError(f"Activity '{activity_id}' feature must be a non-empty string.")
            if known_features and required_feature not in known_features:
                raise ContentError(
                    f"Activity '{activity_id}' references unknown feature '{required_feature}'."
                )
        raw_cost = raw.get("start_cost", 0)
        if isinstance(raw_cost, bool) or not isinstance(raw_cost, int) or raw_cost < 0:
            raise ContentError(f"Activity '{activity_id}' start_cost must be a non-negative integer.")
        raw_record = raw.get("record", False)
        if not isinstance(raw_record, bool):
            raise ContentError(f"Activity '{activity_id}' record must be a boolean.")
        raw_min = raw.get("min_completed_round", 0)
        if isinstance(raw_min, bool) or not isinstance(raw_min, (int, float)) or raw_min < 0:
            raise ContentError(
                f"Activity '{activity_id}' min_completed_round must be a non-negative number."
            )
        definitions[activity_id] = ActivityDefinition(
            id=activity_id,
            title=title,
            room_bound=room_bound,
            aliases=aliases,
            rooms=rooms,
            required_feature=required_feature,
            source=source,
            start_cost=int(raw_cost),
            record=raw_record,
            min_completed_round=float(raw_min),
        )
    return definitions


def merge_activity_definitions(
    core: Mapping[str, ActivityDefinition],
    world: Mapping[str, ActivityDefinition],
) -> dict[str, ActivityDefinition]:
    """Merge core and world catalogs, letting the world override by id."""

    merged = dict(core)
    merged.update(world)
    return merged
