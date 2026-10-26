"""Strict world, room, prop, and peep definition loaders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from server.content.activities import (
    ActivityDefinition,
    load_activity_definitions,
    merge_activity_definitions,
)
from server.content.common import (
    ContentError,
    drop_unknown_card_ids,
    load_yaml_file,
    require_mapping,
    warn_unknown_card,
)
from server.content.conditions import StatusCondition, parse_status_condition
from server.content.cutscenes import (
    CutsceneDefinition,
    load_cutscene_definitions,
    merge_cutscene_definitions,
)
from server.content.fx import load_effect_catalog
from server.content.game_boards import RoomGameDefinition, load_room_game
from server.content.lighting import DEFAULT_LIGHTING_ENVIRONMENT, validate_lighting_name
from server.content.prop_definitions import (
    DEFAULT_PROP_PRICE,
    FREE_PROPSET_SOURCES,
    MOVED_INSTANCE_PROP_FIELDS,
    PROPS_CONFIG_KEY,
    PropDefinition,
    PropInstanceDefinition,
    PropStateDefinition,
    QuickAction,
    builtin_prop_definitions,
    load_prop_definition,
    load_props_scale_adjust,
    load_propset,
    _load_actions,
    _load_animation,
    _load_draw_weight,
    _load_props_from_file,
    _load_text_recipe,
    _load_vec3,
    _validate_prop_effects,
    resolve_default_prop_actions,
)
from server.content.recipes import RecipeDefinition, load_recipes
from server.content.room_environment import load_editor_environment
from server.content.sounds import PROP_SOUND_KEYS, parse_sounds
from server.content.exit_props import load_exit_style
from server.content.surface_props import (
    MAX_SIGN_PROPS,
    MAX_WHITEBOARD_PROPS,
    SIGN_PROP_ID,
    WHITEBOARD_PROP_ID,
    load_authored_surface,
    load_sign_style,
)
from server.content.tasks import TaskDefinition, load_task_definitions
from server.content.text_props import MAX_ROOM_TEXT_LENGTH, MAX_TEXT_PROPS


BOARD_IMAGE_STYLES = frozenset({"stretch", "tile", "tile-w", "tile-h"})
BOARD_TYPES = frozenset({"basic", "diorama"})
POWER_NAMES = ("admin", "realtor", "builder", "moderator", "game-master")
from server.content.prop_assets import (  # noqa: E402
    prop_model_url,
)


@dataclass(frozen=True, slots=True)
class ExitDefinition:
    """An immutable room exit definition."""

    id: str
    label: str
    target_room_id: str
    locked: bool
    requires_card_id: str | None
    npc_barrier: bool = False
    target_world_id: str | None = None


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
    editor_environment: tuple[str, ...] = ()
    template: bool = False
    sprites_enabled: bool = False
    game: RoomGameDefinition | None = None
    environment: str | None = None


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
    vibe_delta: int = 0
    grant_bops: int = 0
    repeatable: bool = False


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

    # activity names a catalog entry; launching through this peep is room-bound.
    # Cutscenes instead use explicit .cutscene actions (including any target
    # placeholder); those command arguments are resolved only when invoked.
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

    # These are authored seeds/catalogs, distinct from live SQLite room state.
    # requires_mods is enforced against enabled mods when that set is supplied.
    # Activities merge core/mod entries with world overrides; cutscene merging
    # rejects duplicate ids/aliases, and card cutscene references are checked here.
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
    cutscenes: dict[str, CutsceneDefinition] = field(default_factory=dict)
    tasks: dict[str, TaskDefinition] = field(default_factory=dict)
    powers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    recipes: dict[str, RecipeDefinition] = field(default_factory=dict)
    requires_mods: tuple[str, ...] = ()
    effects: dict[str, EffectDefinition] = field(default_factory=dict)
    image_name: str = ""
    image_path: Path | None = None
    stylesheet_name: str = ""
    stylesheet_path: Path | None = None
    global_environment: str = "day"


def _load_world_powers(raw_value: Any, world_file: Path) -> dict[str, tuple[str, ...]]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ContentError(f"{world_file} powers must be a mapping of username to power list.")
    powers: dict[str, tuple[str, ...]] = {}
    for username, raw_powers in raw_value.items():
        if not isinstance(username, str) or not username.strip():
            raise ContentError(f"{world_file} powers contains an empty username entry.")
        if not isinstance(raw_powers, list):
            raise ContentError(f"{world_file} powers for '{username}' must be a list.")
        granted: list[str] = []
        for power in raw_powers:
            if not isinstance(power, str) or power not in POWER_NAMES:
                raise ContentError(
                    f"{world_file} powers for '{username}' has unknown power '{power}'. "
                    f"Expected one of {', '.join(POWER_NAMES)}."
                )
            if power not in granted:
                granted.append(power)
        powers[username.strip().casefold()] = tuple(granted)
    return powers


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
    raw_bops = raw_choice.get("grant_bops", 0)
    if isinstance(raw_bops, bool) or not isinstance(raw_bops, int):
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} 'grant_bops' must be an integer.")
    raw_vibe = raw_choice.get("vibe_delta", 0)
    if isinstance(raw_vibe, bool) or not isinstance(raw_vibe, int):
        raise ContentError(f"Peep '{peep_id}' dialog node '{node_id}' choice {index} 'vibe_delta' must be an integer.")
    repeatable = raw_choice.get("repeatable") is True
    if repeatable and (give_card is not None or raw_bops or raw_grant or raw_choice.get("start_task") is not None):
        raise ContentError(
            f"Peep '{peep_id}' dialog node '{node_id}' choice {index} is repeatable "
            "and must not grant cards, Bops, Kudos, or start tasks."
        )
    # Choice order participates in the persistent reward-ledger identity.
    # Inserting or reordering choices can reassign rewards to different actions.
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
        vibe_delta=int(raw_vibe),
        grant_bops=int(raw_bops),
        repeatable=repeatable,
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


def _as_paths(value: Path | Sequence[Path] | None) -> list[Path]:
    """Normalize an optional single path or path sequence into a list."""

    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(root) for root in value]


def _validate_prop_references(
    props: dict[str, PropDefinition],
    recipes: Mapping[str, RecipeDefinition],
    card_ids: set[str],
) -> dict[str, PropDefinition]:
    """Check definition-level recipe references and drop unknown content cards."""

    validated: dict[str, PropDefinition] = {}
    for prop_id, definition in props.items():
        for recipe_id in definition.recipes:
            if recipe_id not in recipes:
                raise ContentError(f"Prop '{prop_id}' references unknown recipe '{recipe_id}'.")
        if not definition.content:
            validated[prop_id] = definition
            continue
        content = tuple(
            drop_unknown_card_ids(definition.content, card_ids, f"Prop '{prop_id}' content")
        )
        validated[prop_id] = replace(definition, content=content) if content != definition.content else definition
    return validated


def _validate_one_per_room(
    props: Mapping[str, PropDefinition],
    room_id: str,
    instances: Iterable[PropInstanceDefinition],
) -> None:
    """Reject rooms placing more than one instance of a one_per_room prop."""

    counts: dict[str, int] = {}
    for instance in instances:
        definition = props[instance.prop_id]
        if not definition.one_per_room:
            continue
        counts[instance.prop_id] = counts.get(instance.prop_id, 0) + 1
        if counts[instance.prop_id] > 1:
            raise ContentError(
                f"Room '{room_id}' may contain only one '{instance.prop_id}' prop."
            )


def load_world_definition(
    world_path: Path,
    card_ids: set[str],
    *,
    core_activities: Mapping[str, ActivityDefinition] | None = None,
    core_cutscenes: Mapping[str, CutsceneDefinition] | None = None,
    cutscene_cards: Sequence[tuple[str, str]] = (),
    cutscene_roots: Sequence[Path] | None = None,
    known_features: frozenset[str] = frozenset(),
    propsets_root: Path | Sequence[Path] | None = None,
    shared_propsets_root: Path | Sequence[Path] | None = None,
    mod_props: Sequence[tuple[str, Path]] | None = None,
    enabled_mods: frozenset[str] | None = None,
    fx_root: Path | None = None,
    extra_recipes: Mapping[str, RecipeDefinition] | None = None,
    known_sounds: frozenset[str] | None = None,
    allow_legacy_whiteboards: bool = False,
) -> WorldDefinition:
    """Load the immutable world definition set from YAML."""

    world_file = world_path / "world.yaml"
    world_payload = require_mapping(load_yaml_file(world_file), world_file)
    world_id = str(world_payload.get("id", "")).strip()
    entry_room_id = str(world_payload.get("entry_room", "")).strip()
    if not world_id or not entry_room_id:
        raise ContentError("world.yaml must define id and entry_room.")
    world_image_name = str(world_payload.get("image", "")).strip()
    world_image_path: Path | None = None
    if world_image_name:
        world_root = world_path.resolve()
        candidate = (world_path / world_image_name).resolve()
        if candidate != world_root and world_root not in candidate.parents:
            raise ContentError(f"World '{world_id}' image path escapes the world directory.")
        if not candidate.is_file():
            raise ContentError(f"World '{world_id}' references missing image '{world_image_name}'.")
        world_image_path = candidate
    stylesheet_name = str(world_payload.get("css", "")).strip()
    stylesheet_path: Path | None = None
    if stylesheet_name:
        world_root = world_path.resolve()
        candidate = (world_path / stylesheet_name).resolve()
        if (
            candidate == world_root
            or world_root not in candidate.parents
            or candidate.suffix.lower() != ".css"
        ):
            raise ContentError(f"World '{world_id}' stylesheet must be a .css file inside the world directory.")
        if not candidate.is_file():
            raise ContentError(f"World '{world_id}' references missing stylesheet '{stylesheet_name}'.")
        stylesheet_path = candidate
    requires_mods = tuple(str(entry).strip() for entry in world_payload.get("requires_mods", []) or [])
    global_environment = validate_lighting_name(
        world_payload.get("environment"), f"World '{world_id}' environment"
    ) or DEFAULT_LIGHTING_ENVIRONMENT
    if enabled_mods is not None:
        missing_mods = sorted(set(requires_mods) - set(enabled_mods))
        if missing_mods:
            raise ContentError(
                f"World '{world_id}' requires mod(s) {missing_mods}; enable them via TRSERVER_MODS."
            )

    props_file = world_path / "props" / "props.yaml"
    rooms_file = world_path / "rooms" / "rooms.yaml"
    peeps_file = world_path / "peeps" / "peeps.yaml"
    rooms_payload = require_mapping(load_yaml_file(rooms_file), rooms_file)
    peeps_payload = require_mapping(load_yaml_file(peeps_file), peeps_file)
    recipes = load_recipes(world_path, card_ids, source=world_id)
    for recipe_id, recipe in (extra_recipes or {}).items():
        if recipe_id in recipes:
            raise ContentError(f"Duplicate recipe id '{recipe_id}'.")
        recipes[recipe_id] = recipe

    props: dict[str, PropDefinition] = {}
    for root in _as_paths(propsets_root):
        for propset_file in sorted(root.glob("*/props.yaml")):
            for prop_id, definition in _load_props_from_file(
                propset_file,
                propset_file.parent.name,
                "propset",
                known_sounds=known_sounds,
            ).items():
                if prop_id in props:
                    raise ContentError(f"Duplicate prop id '{prop_id}'.")
                props[prop_id] = definition
    for root in _as_paths(shared_propsets_root):
        shared_props: dict[str, PropDefinition] = {}
        for propset_file in sorted(root.glob("*/props.yaml")):
            for prop_id, definition in _load_props_from_file(
                propset_file,
                propset_file.parent.name,
                "propset",
                known_sounds=known_sounds,
            ).items():
                if prop_id in shared_props:
                    raise ContentError(f"Duplicate prop id '{prop_id}'.")
                shared_props[prop_id] = definition
        props.update(shared_props)
    for mod_id, props_dir in mod_props or ():
        mod_props_file = Path(props_dir) / "props.yaml"
        if not mod_props_file.is_file():
            continue
        for prop_id, definition in _load_props_from_file(
            mod_props_file,
            mod_id,
            "mod",
            known_sounds=known_sounds,
        ).items():
            if prop_id in props:
                raise ContentError(f"Duplicate prop id '{prop_id}'.")
            props[prop_id] = definition
    for prop_id, definition in _load_props_from_file(
        props_file,
        world_id,
        "world",
        known_sounds=known_sounds,
    ).items():
        if prop_id in props:
            raise ContentError(f"Duplicate prop id '{prop_id}'.")
        props[prop_id] = definition
    props.update(builtin_prop_definitions())
    effects = load_effect_catalog(fx_root)
    if fx_root is not None:
        _validate_prop_effects(props, effects)
    props = _validate_prop_references(props, recipes, card_ids)

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
        board_type = str(raw_room.get("board_type", "basic")).strip() or "basic"
        if board_type not in BOARD_TYPES:
            raise ContentError(
                f"Room '{room_id}' has unknown board_type '{board_type}'. "
                f"Expected one of {', '.join(sorted(BOARD_TYPES))}."
            )
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
            moved = sorted(MOVED_INSTANCE_PROP_FIELDS & set(raw_instance))
            if moved:
                raise ContentError(
                    f"Room '{room_id}' prop '{prop_instance_id}' sets {', '.join(moved)} "
                    "on the instance; define them on the prop instead."
                )
            prop_id = str(raw_instance.get("prop", "")).strip()
            if prop_id not in props:
                raise ContentError(f"Room '{room_id}' references unknown prop '{prop_id}'.")
            raw_exit_to = raw_instance.get("exit_to")
            if raw_exit_to is None:
                exit_to = None
            else:
                if not isinstance(raw_exit_to, str) or not raw_exit_to.strip():
                    raise ContentError(f"Prop '{prop_instance_id}' exit_to must be a non-empty string.")
                exit_to = raw_exit_to.strip()
            only_missing = raw_instance.get("only_missing", False)
            if not isinstance(only_missing, bool):
                raise ContentError(f"Prop '{prop_instance_id}' only_missing must be a boolean.")
            raw_label = raw_instance.get("label")
            if raw_label is not None and not isinstance(raw_label, str):
                raise ContentError(f"Prop '{prop_instance_id}' label must be a string.")
            label = raw_label.strip() if isinstance(raw_label, str) else None
            raw_description = raw_instance.get("description")
            if raw_description is not None and not isinstance(raw_description, str):
                raise ContentError(f"Prop '{prop_instance_id}' description must be a string.")
            description = raw_description.strip() if isinstance(raw_description, str) else None
            room_props[prop_instance_id] = PropInstanceDefinition(
                id=prop_instance_id,
                prop_id=prop_id,
                pos=_load_vec3(raw_instance.get("pos"), f"Room '{room_id}' prop '{prop_instance_id}' pos"),
                rot=_load_vec3(raw_instance.get("rot"), f"Room '{room_id}' prop '{prop_instance_id}' rot"),
                scale=float(raw_instance.get("scale", 1.0)),
                actions=_load_actions(raw_instance.get("actions")),
                personal=bool(raw_instance.get("personal", False)),
                animation=_load_animation(
                    raw_instance.get("animation"),
                    f"Room '{room_id}' prop '{prop_instance_id}' animation",
                ),
                draw_weight=_load_draw_weight(raw_instance.get("draw_weight"), prop_instance_id, card_ids),
                only_missing=only_missing,
                text=_load_text_recipe(
                    raw_instance, props[prop_id].render_kind, room_id, prop_instance_id
                ),
                sign_style=load_sign_style(
                    raw_instance,
                    props[prop_id].render_kind,
                    f"Room '{room_id}' prop '{prop_instance_id}'",
                ),
                surface=load_authored_surface(
                    raw_instance,
                    props[prop_id].render_kind,
                    f"Room '{room_id}' prop '{prop_instance_id}' surface",
                    allow_legacy_whiteboards=allow_legacy_whiteboards,
                ),
                sounds=parse_sounds(
                    raw_instance.get("sounds"),
                    f"Room '{room_id}' prop '{prop_instance_id}'",
                    PROP_SOUND_KEYS,
                    known_sounds=known_sounds,
                ),
                description=description or None,
                label=label or None,
                exit_to=exit_to,
                exit_style=load_exit_style(
                    raw_instance,
                    props[prop_id].render_kind,
                    f"Room '{room_id}' prop '{prop_instance_id}'",
                ),
            )
        _validate_one_per_room(props, room_id, room_props.values())
        texts = [instance.text for instance in room_props.values() if instance.text is not None]
        if len(texts) > MAX_TEXT_PROPS:
            raise ContentError(f"Room '{room_id}' may contain at most {MAX_TEXT_PROPS} text props.")
        if sum(len(text["content"]) for text in texts) > MAX_ROOM_TEXT_LENGTH:
            raise ContentError(
                f"Room '{room_id}' text props may contain at most {MAX_ROOM_TEXT_LENGTH} total characters."
            )
        if sum(1 for instance in room_props.values() if instance.prop_id == SIGN_PROP_ID) > MAX_SIGN_PROPS:
            raise ContentError(f"Room '{room_id}' may contain at most {MAX_SIGN_PROPS} signs.")
        if sum(1 for instance in room_props.values() if instance.prop_id == WHITEBOARD_PROP_ID) > MAX_WHITEBOARD_PROPS:
            raise ContentError(f"Room '{room_id}' may contain at most {MAX_WHITEBOARD_PROPS} whiteboards.")
        raw_exits = raw_room.get("exits", {}) or {}
        if not isinstance(raw_exits, dict):
            raise ContentError(f"Room '{room_id}' exits must be a mapping.")
        room_exits: dict[str, ExitDefinition] = {}
        for exit_id, raw_exit in raw_exits.items():
            if not isinstance(raw_exit, dict):
                raise ContentError(f"Room '{room_id}' has an invalid exit '{exit_id}'.")
            requires_card_id = str(raw_exit["requires"]) if "requires" in raw_exit else None
            if requires_card_id is not None and requires_card_id not in card_ids:
                warn_unknown_card(f"Exit '{room_id}.{exit_id}' requires", requires_card_id)
                requires_card_id = None
            target_world_id = str(raw_exit["target_world"]).strip() if raw_exit.get("target_world") else None
            target_room_id = str(raw_exit.get("target", "")).strip()
            if target_world_id is None and not target_room_id:
                raise ContentError(f"Exit '{room_id}.{exit_id}' must define a target room or target world.")
            room_exits[exit_id] = ExitDefinition(
                id=exit_id,
                label=str(raw_exit.get("label", "")).strip(),
                target_room_id=target_room_id,
                locked=bool(raw_exit.get("locked", False)),
                requires_card_id=requires_card_id,
                npc_barrier=bool(raw_exit.get("npc_barrier", False)),
                target_world_id=target_world_id,
            )
        for instance in room_props.values():
            if instance.exit_to is not None and instance.exit_to not in room_exits:
                raise ContentError(
                    f"Room '{room_id}' prop '{instance.id}' exit_to references unknown exit '{instance.exit_to}'."
                )
        room_cards: list[InitialRoomCard] = []
        for index, raw_card in enumerate(raw_room.get("cards", []) or []):
            if not isinstance(raw_card, dict):
                raise ContentError(f"Room '{room_id}' contains an invalid card entry.")
            card_id = str(raw_card.get("card", "")).strip()
            if card_id not in card_ids:
                warn_unknown_card(f"Room '{room_id}'", card_id)
                continue
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
        game = load_room_game(
            raw_room.get("game"),
            world_root=world_path,
            room_id=room_id,
            room_props=room_props,
            props=props,
            effects=effects,
            power_names=POWER_NAMES,
        )
        rooms[room_id] = RoomDefinition(
            id=room_id,
            label=str(raw_room.get("label", "")).strip(),
            description=str(raw_room.get("description", "")).strip(),
            board_type=board_type,
            board_image_name=board_image_name,
            board_image_path=board_image_path,
            board_image_style=board_image_style,
            palette=tuple(str(value) for value in raw_room.get("palette", []) or []),
            dark=bool(raw_room.get("dark", False)),
            props=room_props,
            exits=room_exits,
            initial_cards=tuple(room_cards),
            editor_environment=load_editor_environment(raw_room.get("editor"), room_id),
            template=bool(raw_room.get("template", False)),
            sprites_enabled=bool(raw_room.get("sprites_enabled", False)),
            game=game,
            environment=validate_lighting_name(
                raw_room.get("environment"), f"Room '{room_id}' environment"
            ),
        )

    if entry_room_id not in rooms:
        raise ContentError(f"World entry room '{entry_room_id}' does not exist.")
    for room in rooms.values():
        for exit_definition in room.exits.values():
            if exit_definition.target_world_id is not None:
                continue
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
    for definition in props.values():
        if definition.activity and definition.activity not in activities:
            raise ContentError(
                f"Prop '{definition.id}' references unknown activity '{definition.activity}'."
            )
    for peep in peeps.values():
        if peep.activity and peep.activity not in activities:
            raise ContentError(f"Peep '{peep.id}' references unknown activity '{peep.activity}'.")

    roots: list[Path] = [Path(root) for root in (cutscene_roots or ())]
    roots.insert(0, world_path / "cutscenes")
    world_cutscenes = load_cutscene_definitions(
        world_path / "cutscenes.yaml",
        source=world_id,
        script_roots=roots,
        known_rooms=frozenset(rooms),
        known_features=known_features,
        known_powers=frozenset(POWER_NAMES),
        known_sounds=known_sounds,
    )
    cutscenes = merge_cutscene_definitions(core_cutscenes or {}, world_cutscenes)
    # Cross-content validation currently accepts direct ids only, not aliases.
    # Authored .cutscene quick-action strings are not cross-validated here.
    for card_id, cutscene_id in cutscene_cards:
        if cutscene_id not in cutscenes:
            raise ContentError(f"Card '{card_id}' references unknown cutscene '{cutscene_id}'.")

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
        cutscenes=cutscenes,
        tasks=load_task_definitions(world_path, card_ids, known_sounds=known_sounds),
        powers=_load_world_powers(world_payload.get("powers"), world_file),
        recipes=recipes,
        requires_mods=requires_mods,
    effects=effects,
    image_name=world_image_name,
    image_path=world_image_path,
    stylesheet_name=stylesheet_name,
    stylesheet_path=stylesheet_path,
    global_environment=global_environment,
)
