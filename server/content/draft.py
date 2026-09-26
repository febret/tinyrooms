"""Draft content-graph normalization shared by the World Editor and Publish."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from server.content.common import ContentError
from server.content.worlds import PROPS_CONFIG_KEY


DRAFT_FORMAT_VERSION = 1

_SECTION_FILES: tuple[tuple[str, str], ...] = (
    ("world", "world.yaml"),
    ("props", "props/props.yaml"),
    ("rooms", "rooms/rooms.yaml"),
    ("peeps", "peeps/peeps.yaml"),
    ("recipes", "recipes.yaml"),
    ("tasks", "tasks.yaml"),
    ("activities", "activities.yaml"),
)

_YAML_FILE_ORDER: tuple[str, ...] = tuple(file_name for _, file_name in _SECTION_FILES)


@dataclass(frozen=True, slots=True)
class DraftIssue:
    """A structural validation error with a field path."""

    path: str
    message: str

    def to_payload(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""

        return {"path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class DraftReferences:
    """Known identifiers a draft may reference."""

    card_ids: frozenset[str] = frozenset()
    prop_ids: frozenset[str] = frozenset()
    activity_ids: frozenset[str] = frozenset()
    recipe_ids: frozenset[str] = frozenset()


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ContentError(f"{path} must contain a top-level mapping.")
    return raw


def build_draft(world_path: Path, *, world_id: str) -> dict[str, Any]:
    """Build a fresh draft by copying the published YAML sections."""

    draft: dict[str, Any] = {
        "format_version": DRAFT_FORMAT_VERSION,
        "world_id": world_id,
        "draft_revision": 0,
        "base_published_revision": None,
        "updated_at": None,
    }
    for section, file_name in _SECTION_FILES:
        draft[section] = _read_mapping(world_path / file_name)
    return draft


def draft_yaml_files(draft: dict[str, Any]) -> dict[str, object]:
    """Return the YAML file payloads a draft serializes to."""

    files: dict[str, object] = {}
    for section, file_name in _SECTION_FILES:
        payload = draft.get(section)
        files[file_name] = payload if isinstance(payload, dict) else {}
    return files


def yaml_file_names() -> tuple[str, ...]:
    """Return the editable YAML file names in publish order."""

    return _YAML_FILE_ORDER


def _issue(issues: list[DraftIssue], path: str, message: str) -> None:
    issues.append(DraftIssue(path=path, message=message))


def _check_identifier_list(
    issues: list[DraftIssue],
    value: Any,
    path: str,
    known: frozenset[str],
    label: str,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        _issue(issues, path, f"{label} must be a list.")
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry:
            _issue(issues, f"{path}[{index}]", f"{label} entries must be non-empty strings.")
        elif known and entry not in known:
            _issue(issues, f"{path}[{index}]", f"Unknown {label[:-1]} '{entry}'.")


def _check_rooms(issues: list[DraftIssue], rooms: Any, references: DraftReferences) -> None:
    if not isinstance(rooms, dict) or not rooms:
        _issue(issues, "rooms", "At least one room is required.")
        return
    room_ids = frozenset(rooms)
    for room_id, room in rooms.items():
        base = f"rooms.{room_id}"
        if not isinstance(room_id, str) or not room_id:
            _issue(issues, base, "Room id must be a non-empty string.")
        if not isinstance(room, dict):
            _issue(issues, base, "Room must be a mapping.")
            continue
        for field_name in ("label", "board_image"):
            if not isinstance(room.get(field_name), str) or not room.get(field_name):
                _issue(issues, f"{base}.{field_name}", f"Room {field_name} is required.")
        props = room.get("props")
        if props is not None:
            if not isinstance(props, dict):
                _issue(issues, f"{base}.props", "props must be a mapping.")
            else:
                for instance_id, instance in props.items():
                    instance_path = f"{base}.props.{instance_id}"
                    if not isinstance(instance, dict):
                        _issue(issues, instance_path, "Prop instance must be a mapping.")
                        continue
                    prop_id = instance.get("prop")
                    if not isinstance(prop_id, str) or not prop_id:
                        _issue(issues, f"{instance_path}.prop", "Prop reference is required.")
                    elif references.prop_ids and prop_id not in references.prop_ids:
                        _issue(issues, f"{instance_path}.prop", f"Unknown prop '{prop_id}'.")
                    _check_identifier_list(
                        issues, instance.get("content"), f"{instance_path}.content",
                        references.card_ids, "cards",
                    )
                    _check_identifier_list(
                        issues, instance.get("recipes"), f"{instance_path}.recipes",
                        references.recipe_ids, "recipes",
                    )
                    activity = instance.get("activity")
                    if activity is not None and (
                        not isinstance(activity, str)
                        or (references.activity_ids and activity not in references.activity_ids)
                    ):
                        _issue(issues, f"{instance_path}.activity", f"Unknown activity '{activity}'.")
        exits = room.get("exits")
        if exits is not None:
            if not isinstance(exits, dict):
                _issue(issues, f"{base}.exits", "exits must be a mapping.")
            else:
                for exit_id, exit_definition in exits.items():
                    exit_path = f"{base}.exits.{exit_id}"
                    if not isinstance(exit_definition, dict):
                        _issue(issues, exit_path, "Exit must be a mapping.")
                        continue
                    target = exit_definition.get("target")
                    if not isinstance(target, str) or not target:
                        _issue(issues, f"{exit_path}.target", "Exit target is required.")
                    elif target not in room_ids:
                        _issue(issues, f"{exit_path}.target", f"Exit target '{target}' is not a room.")
        cards = room.get("cards")
        if cards is not None:
            if not isinstance(cards, list):
                _issue(issues, f"{base}.cards", "Initial room cards must be a list.")
            else:
                for index, card in enumerate(cards):
                    card_path = f"{base}.cards[{index}]"
                    if not isinstance(card, dict):
                        _issue(issues, card_path, "Initial room card must be a mapping.")
                        continue
                    card_id = card.get("card")
                    if not isinstance(card_id, str) or not card_id:
                        _issue(issues, f"{card_path}.card", "Card reference is required.")
                    elif references.card_ids and card_id not in references.card_ids:
                        _issue(issues, f"{card_path}.card", f"Unknown card '{card_id}'.")


def _check_world(issues: list[DraftIssue], world: Any, room_ids: frozenset[str]) -> None:
    if not isinstance(world, dict):
        _issue(issues, "world", "World must be a mapping.")
        return
    if not isinstance(world.get("id"), str) or not world.get("id"):
        _issue(issues, "world.id", "World id is required.")
    entry_room = world.get("entry_room")
    if not isinstance(entry_room, str) or not entry_room:
        _issue(issues, "world.entry_room", "Entry room is required.")
    elif room_ids and entry_room not in room_ids:
        _issue(issues, "world.entry_room", f"Entry room '{entry_room}' is not defined.")


def _check_peeps(issues: list[DraftIssue], peeps: Any, room_ids: frozenset[str]) -> None:
    if peeps is None:
        return
    if not isinstance(peeps, dict):
        _issue(issues, "peeps", "peeps must be a mapping.")
        return
    for peep_id, peep in peeps.items():
        base = f"peeps.{peep_id}"
        if not isinstance(peep, dict):
            _issue(issues, base, "Peep must be a mapping.")
            continue
        if not isinstance(peep.get("label"), str) or not peep.get("label"):
            _issue(issues, f"{base}.label", "Peep label is required.")
        room = peep.get("room")
        if not isinstance(room, str) or not room:
            _issue(issues, f"{base}.room", "Peep room is required.")
        elif room_ids and room not in room_ids:
            _issue(issues, f"{base}.room", f"Unknown room '{room}'.")
        dialog = peep.get("dialog")
        if dialog is not None:
            _check_dialog(issues, dialog, f"{base}.dialog")


def _check_dialog(issues: list[DraftIssue], dialog: Any, base: str) -> None:
    if not isinstance(dialog, dict) or not dialog:
        _issue(issues, base, "Dialog must be a non-empty mapping.")
        return
    if "start" not in dialog:
        _issue(issues, base, "Dialog requires a 'start' node.")
    for node_id, node in dialog.items():
        node_path = f"{base}.{node_id}"
        if not isinstance(node, dict):
            _issue(issues, node_path, "Dialog node must be a mapping.")
            continue
        choices = node.get("choices")
        if not isinstance(choices, list):
            _issue(issues, f"{node_path}.choices", "Dialog node requires a choices list.")
            continue
        for index, choice in enumerate(choices):
            choice_path = f"{node_path}.choices[{index}]"
            if not isinstance(choice, dict):
                _issue(issues, choice_path, "Dialog choice must be a mapping.")
                continue
            if not isinstance(choice.get("label"), str) or not choice.get("label"):
                _issue(issues, f"{choice_path}.label", "Choice label is required.")
            next_node = choice.get("next")
            if next_node is not None and next_node not in dialog:
                _issue(issues, f"{choice_path}.next", f"Unknown dialog node '{next_node}'.")


def validate_structure(draft: dict[str, Any], references: DraftReferences) -> list[DraftIssue]:
    """Validate a draft's shape and reference targets without touching assets."""

    issues: list[DraftIssue] = []
    if not isinstance(draft, dict):
        return [DraftIssue(path="draft", message="Draft must be a mapping.")]
    rooms = draft.get("rooms")
    room_ids = frozenset(rooms) if isinstance(rooms, dict) else frozenset()
    _check_world(issues, draft.get("world"), room_ids)
    _check_rooms(issues, rooms, references)
    _check_peeps(issues, draft.get("peeps"), room_ids)
    props = draft.get("props")
    if props is not None:
        if not isinstance(props, dict):
            _issue(issues, "props", "props must be a mapping.")
        else:
            for prop_id, prop in props.items():
                if prop_id == PROPS_CONFIG_KEY:
                    continue
                prop_path = f"props.{prop_id}"
                if not isinstance(prop, dict):
                    _issue(issues, prop_path, "Prop must be a mapping.")
                    continue
                if not isinstance(prop.get("model"), str) or not prop.get("model"):
                    _issue(issues, f"{prop_path}.model", "Prop model is required.")
    recipes = draft.get("recipes")
    if recipes is not None and not isinstance(recipes, dict):
        _issue(issues, "recipes", "recipes must be a mapping.")
    tasks = draft.get("tasks")
    if tasks is not None and not isinstance(tasks, dict):
        _issue(issues, "tasks", "tasks must be a mapping.")
    activities = draft.get("activities")
    if activities is not None and not isinstance(activities, dict):
        _issue(issues, "activities", "activities must be a mapping.")
    return issues


@dataclass(slots=True)
class DraftInfo:
    """Summary of a persisted draft."""

    world_id: str
    draft_revision: int
    base_published_revision: str | None
    updated_at: str | None
    sections: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {
            "world_id": self.world_id,
            "draft_revision": self.draft_revision,
            "base_published_revision": self.base_published_revision,
            "updated_at": self.updated_at,
            "sections": list(self.sections),
        }
