"""Strict world, room, prop, and peep definition loaders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.content.activities import (
    ActivityDefinition,
    load_activity_definitions,
    merge_activity_definitions,
)
from server.content.common import ContentError, load_yaml_file, require_mapping
from server.content.conditions import StatusCondition, parse_status_condition
from server.content.tasks import TaskDefinition, load_task_definitions


BOARD_IMAGE_STYLES = frozenset({"stretch", "tile", "tile-w", "tile-h"})


@dataclass(frozen=True, slots=True)
class QuickAction:
    """A server-provided quick action template."""

    label: str
    command: str


@dataclass(frozen=True, slots=True)
class ExitDefinition:
    """An immutable room exit definition."""

    id: str
    label: str
    target_room_id: str
    locked: bool
    requires_card_id: str | None


@dataclass(frozen=True, slots=True)
class PropDefinition:
    """An immutable prop definition."""

    id: str
    label: str
    description: str
    model_name: str
    model_path: Path
    decorative: bool
    animation: str | None
    scale: float


@dataclass(frozen=True, slots=True)
class PropInstanceDefinition:
    """A prop instance placed into a room."""

    id: str
    prop_id: str
    pos: tuple[float, float, float]
    rot: tuple[float, float, float]
    scale: float
    behavior: str | None
    actions: tuple[QuickAction, ...]
    content: tuple[str, ...]
    cooldown: int | None
    personal: bool
    recipes: tuple[str, ...]
    animation: str | None
    activity: str | None


@dataclass(frozen=True, slots=True)
class InitialRoomCard:
    """An initial room card stack definition."""

    card_id: str
    quantity: int
    pos: tuple[float, float, float]
    initial_key: str


@dataclass(frozen=True, slots=True)
class RoomDefinition:
    """An immutable room definition."""

    id: str
    label: str
    description: str
    board_type: str
    board_image_name: str
    board_image_path: Path
    board_image_style: str
    palette: tuple[str, ...]
    dark: bool
    props: dict[str, PropInstanceDefinition]
    exits: dict[str, ExitDefinition]
    initial_cards: tuple[InitialRoomCard, ...]


@dataclass(frozen=True, slots=True)
class DialogChoice:
    """One authored dialog option and its declarative effects."""

    index: int
    label: str
    action_id: str
    next_node_id: str | None
    end: bool
    when: StatusCondition | None
    script: str | None
    action: str | None
    give_card: str | None
    start_task: str | None
    grant: int


@dataclass(frozen=True, slots=True)
class DialogNode:
    """A single authored dialog node with its ordered choices."""

    id: str
    text: str
    choices: tuple[DialogChoice, ...]


@dataclass(frozen=True, slots=True)
class DialogDefinition:
    """A validated declarative dialog tree."""

    start_node_id: str
    nodes: dict[str, DialogNode]


@dataclass(frozen=True, slots=True)
class PeepDefinition:
    """An immutable NPC definition."""

    id: str
    label: str
    description: str
    room_id: str
    image_name: str
    image_path: Path
    script_name: str | None
    actions: tuple[QuickAction, ...]
    dialog: DialogDefinition | None
    activity: str | None


@dataclass(frozen=True, slots=True)
class WorldDefinition:
    """The fully loaded immutable world definition set."""

    id: str
    label: str
    description: str
    entry_room_id: str
    palette: tuple[str, ...]
    root_path: Path
    props: dict[str, PropDefinition]
    rooms: dict[str, RoomDefinition]
    peeps: dict[str, PeepDefinition]
    activities: dict[str, ActivityDefinition] = field(default_factory=dict)
    tasks: dict[str, TaskDefinition] = field(default_factory=dict)


def _load_actions(raw_value: Any) -> tuple[QuickAction, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError("Actions must be a list.")
    actions: list[QuickAction] = []
    for entry in raw_value:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ContentError("Each action must be a [label, command] pair.")
        label, command = entry
        if not isinstance(label, str) or not isinstance(command, str):
            raise ContentError("Action label and command must be strings.")
        actions.append(QuickAction(label=label.strip(), command=command.strip()))
    return tuple(actions)


def _load_vec3(raw_value: Any, label: str) -> tuple[float, float, float]:
    if raw_value is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise ContentError(f"{label} must be a 3-item list.")
    return (float(raw_value[0]), float(raw_value[1]), float(raw_value[2]))


def _load_animation(raw_value: Any, label: str) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ContentError(f"{label} must be a string.")
    text = raw_value.strip()
    return text or None


def _parse_dialog_condition(raw_value: Any, peep_id: str, node_id: str, index: int) -> StatusCondition | None:
    label = f"Peep '{peep_id}' dialog node '{node_id}' choice {index} 'when'"
    return parse_status_condition(raw_value, label)


def _parse_dialog_choice(
    raw_choice: Any,
    *,
    peep_id: str,
    node_id: str,
    index: int,
    card_ids: set[str],
) -> DialogChoice:
    if not isinstance(raw_choice, dict):
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} must be a mapping.")
    label = str(raw_choice.get("label", "")).strip()
    if not label:
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} must define a label.")
    raw_next = raw_choice.get("next")
    has_end = raw_choice.get("end") is True
    if (raw_next is None) == (not has_end):
        raise ContentError(
            f"Peep '{peep_id}' dialog node '{node_id}' choice {index} must define exactly one of 'next' or 'end: true'."
        )
    next_node_id = str(raw_next).strip() if raw_next is not None else None
    if next_node_id is not None and not next_node_id:
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} has an empty 'next'.")
    give_card = str(raw_choice["give_card"]).strip() if raw_choice.get("give_card") is not None else None
    if give_card is not None and give_card not in card_ids:
        raise ContentError(f"Peep '{peep_id}' dialog choice '{give_card}' references an unknown card.")
    raw_grant = raw_choice.get("grant")
    if raw_grant is not None and (isinstance(raw_grant, bool) or not isinstance(raw_grant, int)):
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} 'grant' must be an integer.")
    return DialogChoice(
        index=index,
        label=label,
        action_id=f"{node_id}:{index}",
        next_node_id=next_node_id,
        end=has_end,
        when=_parse_dialog_condition(raw_choice.get("when"), peep_id, node_id, index),
        script=str(raw_choice["script"]).strip() if raw_choice.get("script") is not None else None,
        action=str(raw_choice["action"]).strip() if raw_choice.get("action") is not None else None,
        give_card=give_card,
        start_task=str(raw_choice["start_task"]).strip() if raw_choice.get("start_task") is not None else None,
        grant=int(raw_grant) if raw_grant is not None else 0,
    )


def _load_dialog(raw_value: Any, peep_id: str, card_ids: set[str]) -> DialogDefinition | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict) or not raw_value:
        raise ContentError(f"Peep '{peep_id}' dialog must be a non-empty mapping.")
    nodes: dict[str, DialogNode] = {}
    for node_id, raw_node in raw_value.items():
        if not isinstance(node_id, str) or not isinstance(raw_node, dict):
            raise ContentError(f"Peep '{peep_id}' has an invalid dialog node entry.")
        text = str(raw_node.get("text", "")).strip()
        if not text:
            raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' must define non-empty text.")
        raw_choices = raw_node.get("choices", []) or []
        if not isinstance(raw_choices, list):
            raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choices must be a list.")
        choices = tuple(
            _parse_dialog_choice(raw_choice, peep_id=peep_id, node_id=node_id, index=index, card_ids=card_ids)
            for index, raw_choice in enumerate(raw_choices)
        )
        nodes[node_id] = DialogNode(id=node_id, text=text, choices=choices)
    if "start" not in nodes:
        raise ContentError(f"Peep '{peep_id}' dialog must define a 'start' node.")
    for node in nodes.values():
        for choice in node.choices:
            if choice.next_node_id is not None and choice.next_node_id not in nodes:
                raise ContentError(
                    f"Peep '{peep_id}' dialog node '{node.id}' choice '{choice.label}' "
                    f"targets missing node '{choice.next_node_id}'."
                )
    reachable = {"start"}
    frontier = ["start"]
    while frontier:
        current = nodes[frontier.pop()]
        for choice in current.choices:
            if choice.next_node_id is not None and choice.next_node_id not in reachable:
                reachable.add(choice.next_node_id)
                frontier.append(choice.next_node_id)
    unreachable = sorted(node_id for node_id in nodes if node_id not in reachable and not node_id.startswith("unused_"))
    if unreachable:
        raise ContentError(f"Peep '{peep_id}' dialog has unreachable nodes {unreachable}.")
    return DialogDefinition(start_node_id="start", nodes=nodes)


def load_world_definition(
    world_path: Path,
    card_ids: set[str],
    *,
    core_activities: Mapping[str, ActivityDefinition] | None = None,
    known_features: frozenset[str] = frozenset(),
) -> WorldDefinition:
    """Load the immutable world definition set from YAML."""

    world_file = world_path / "world.yaml"
    world_payload = require_mapping(load_yaml_file(world_file), world_file)
    world_id = str(world_payload.get("id", "")).strip()
    entry_room_id = str(world_payload.get("entry_room", "")).strip()
    if not world_id or not entry_room_id:
        raise ContentError("world.yaml must define id and entry_room.")

    props_file = world_path / "props" / "props.yaml"
    rooms_file = world_path / "rooms" / "rooms.yaml"
    peeps_file = world_path / "peeps" / "peeps.yaml"
    props_payload = require_mapping(load_yaml_file(props_file), props_file)
    rooms_payload = require_mapping(load_yaml_file(rooms_file), rooms_file)
    peeps_payload = require_mapping(load_yaml_file(peeps_file), peeps_file)

    props: dict[str, PropDefinition] = {}
    for prop_id, raw_prop in props_payload.items():
        if not isinstance(prop_id, str) or not isinstance(raw_prop, dict):
            raise ContentError(f"{props_file} contains an invalid prop entry.")
        model_name = str(raw_prop.get("model", "")).strip()
        if not model_name:
            raise ContentError(f"Prop '{prop_id}' is missing its model.")
        model_path = (props_file.parent / model_name).resolve()
        if not model_path.is_file():
            raise ContentError(f"Prop '{prop_id}' references missing model '{model_name}'.")
        raw_scale = raw_prop.get("scale", 1.0)
        if isinstance(raw_scale, bool) or not isinstance(raw_scale, (int, float)) or float(raw_scale) <= 0:
            raise ContentError(f"Prop '{prop_id}' has an invalid scale {raw_scale!r}.")
        scale = float(raw_scale)
        props[prop_id] = PropDefinition(
            id=prop_id,
            label=str(raw_prop.get("label", "")).strip(),
            description=str(raw_prop.get("description", "")).strip(),
            model_name=model_name,
            model_path=model_path,
            decorative=bool(raw_prop.get("decorative", False)),
            animation=_load_animation(raw_prop.get("animation"), f"Prop '{prop_id}' animation"),
            scale=scale,
        )

    rooms: dict[str, RoomDefinition] = {}
    for room_id, raw_room in rooms_payload.items():
        if not isinstance(room_id, str) or not isinstance(raw_room, dict):
            raise ContentError(f"{rooms_file} contains an invalid room entry.")
        board_image_name = str(raw_room.get("board_image", "")).strip()
        if not board_image_name:
            raise ContentError(f"Room '{room_id}' is missing board_image.")
        board_image_path = (rooms_file.parent / board_image_name).resolve()
        if not board_image_path.is_file():
            raise ContentError(f"Room '{room_id}' references missing board image '{board_image_name}'.")
        board_image_style = str(raw_room.get("board_image_style", "stretch")).strip() or "stretch"
        if board_image_style not in BOARD_IMAGE_STYLES:
            raise ContentError(
                f"Room '{room_id}' has unknown board_image_style '{board_image_style}'. "
                f"Expected one of {', '.join(sorted(BOARD_IMAGE_STYLES))}."
            )
        raw_props = raw_room.get("props", {}) or {}
        if not isinstance(raw_props, dict):
            raise ContentError(f"Room '{room_id}' props must be a mapping.")
        room_props: dict[str, PropInstanceDefinition] = {}
        for prop_instance_id, raw_instance in raw_props.items():
            if not isinstance(raw_instance, dict):
                raise ContentError(f"Room '{room_id}' has an invalid prop instance '{prop_instance_id}'.")
            prop_id = str(raw_instance.get("prop", "")).strip()
            if prop_id not in props:
                raise ContentError(f"Room '{room_id}' references unknown prop '{prop_id}'.")
            content = tuple(str(card_id) for card_id in raw_instance.get("content", []) or [])
            for card_id in content:
                if card_id not in card_ids:
                    raise ContentError(f"Prop '{prop_instance_id}' references unknown card '{card_id}'.")
            room_props[prop_instance_id] = PropInstanceDefinition(
                id=prop_instance_id,
                prop_id=prop_id,
                pos=_load_vec3(raw_instance.get("pos"), f"Room '{room_id}' prop '{prop_instance_id}' pos"),
                rot=_load_vec3(raw_instance.get("rot"), f"Room '{room_id}' prop '{prop_instance_id}' rot"),
                scale=float(raw_instance.get("scale", 1.0)),
                behavior=str(raw_instance["behavior"]) if "behavior" in raw_instance else None,
                actions=_load_actions(raw_instance.get("actions")),
                content=content,
                cooldown=int(raw_instance["cooldown"]) if "cooldown" in raw_instance else None,
                personal=bool(raw_instance.get("personal", False)),
                recipes=tuple(str(value) for value in raw_instance.get("recipes", []) or []),
                animation=_load_animation(
                    raw_instance.get("animation"),
                    f"Room '{room_id}' prop '{prop_instance_id}' animation",
                ),
                activity=str(raw_instance["activity"]).strip() if raw_instance.get("activity") else None,
            )
        raw_exits = raw_room.get("exits", {}) or {}
        if not isinstance(raw_exits, dict):
            raise ContentError(f"Room '{room_id}' exits must be a mapping.")
        room_exits: dict[str, ExitDefinition] = {}
        for exit_id, raw_exit in raw_exits.items():
            if not isinstance(raw_exit, dict):
                raise ContentError(f"Room '{room_id}' has an invalid exit '{exit_id}'.")
            requires_card_id = str(raw_exit["requires"]) if "requires" in raw_exit else None
            if requires_card_id is not None and requires_card_id not in card_ids:
                raise ContentError(f"Exit '{room_id}.{exit_id}' requires unknown card '{requires_card_id}'.")
            room_exits[exit_id] = ExitDefinition(
                id=exit_id,
                label=str(raw_exit.get("label", "")).strip(),
                target_room_id=str(raw_exit.get("target", "")).strip(),
                locked=bool(raw_exit.get("locked", False)),
                requires_card_id=requires_card_id,
            )
        room_cards: list[InitialRoomCard] = []
        for index, raw_card in enumerate(raw_room.get("cards", []) or []):
            if not isinstance(raw_card, dict):
                raise ContentError(f"Room '{room_id}' contains an invalid card entry.")
            card_id = str(raw_card.get("card", "")).strip()
            if card_id not in card_ids:
                raise ContentError(f"Room '{room_id}' references unknown card '{card_id}'.")
            quantity = int(raw_card.get("quantity", 1))
            if quantity < 1:
                raise ContentError(f"Room '{room_id}' has invalid quantity {quantity} for '{card_id}'.")
            room_cards.append(
                InitialRoomCard(
                    card_id=card_id,
                    quantity=quantity,
                    pos=_load_vec3(raw_card.get("pos"), f"Room '{room_id}' card '{card_id}' pos"),
                    initial_key=f"{room_id}:{index}:{card_id}",
                )
            )
        rooms[room_id] = RoomDefinition(
            id=room_id,
            label=str(raw_room.get("label", "")).strip(),
            description=str(raw_room.get("description", "")).strip(),
            board_type=str(raw_room.get("board_type", "basic")).strip(),
            board_image_name=board_image_name,
            board_image_path=board_image_path,
            board_image_style=board_image_style,
            palette=tuple(str(value) for value in raw_room.get("palette", []) or []),
            dark=bool(raw_room.get("dark", False)),
            props=room_props,
            exits=room_exits,
            initial_cards=tuple(room_cards),
        )

    if entry_room_id not in rooms:
        raise ContentError(f"World entry room '{entry_room_id}' does not exist.")
    for room in rooms.values():
        for exit_definition in room.exits.values():
            if exit_definition.target_room_id not in rooms:
                raise ContentError(
                    f"Room '{room.id}' exit '{exit_definition.id}' targets unknown room "
                    f"'{exit_definition.target_room_id}'."
                )

    peeps: dict[str, PeepDefinition] = {}
    for peep_id, raw_peep in peeps_payload.items():
        if not isinstance(peep_id, str) or not isinstance(raw_peep, dict):
            raise ContentError(f"{peeps_file} contains an invalid peep entry.")
        room_id = str(raw_peep.get("room", "")).strip()
        if room_id not in rooms:
            raise ContentError(f"Peep '{peep_id}' references unknown room '{room_id}'.")
        image_name = str(raw_peep.get("image", "")).strip()
        image_path = (peeps_file.parent / image_name).resolve()
        if not image_name or not image_path.is_file():
            raise ContentError(f"Peep '{peep_id}' references missing image '{image_name}'.")
        peeps[peep_id] = PeepDefinition(
            id=peep_id,
            label=str(raw_peep.get("label", "")).strip(),
            description=str(raw_peep.get("description", "")).strip(),
            room_id=room_id,
            image_name=image_name,
            image_path=image_path,
            script_name=str(raw_peep["script"]) if "script" in raw_peep else None,
            actions=_load_actions(raw_peep.get("actions")),
            dialog=_load_dialog(raw_peep.get("dialog"), peep_id, card_ids),
            activity=str(raw_peep["activity"]).strip() if raw_peep.get("activity") else None,
        )

    world_activities = load_activity_definitions(
        world_path / "activities.yaml",
        source=world_id,
        known_rooms=frozenset(rooms),
        known_features=known_features,
    )
    activities = merge_activity_definitions(core_activities or {}, world_activities)
    for room in rooms.values():
        for prop in room.props.values():
            if prop.activity and prop.activity not in activities:
                raise ContentError(
                    f"Room '{room.id}' prop '{prop.id}' references unknown activity '{prop.activity}'."
                )
    for peep in peeps.values():
        if peep.activity and peep.activity not in activities:
            raise ContentError(f"Peep '{peep.id}' references unknown activity '{peep.activity}'.")

    return WorldDefinition(
        id=world_id,
        label=str(world_payload.get("label", "")).strip(),
        description=str(world_payload.get("description", "")).strip(),
        entry_room_id=entry_room_id,
        palette=tuple(str(value) for value in world_payload.get("palette", []) or []),
        root_path=world_path.resolve(),
        props=props,
        rooms=rooms,
        peeps=peeps,
        activities=activities,
        tasks=load_task_definitions(world_path, card_ids),
    )
