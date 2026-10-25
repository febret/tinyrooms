"""Prop definition and prop instance loaders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.content.common import LOGGER, ContentError, load_yaml_file, require_mapping, warn_unknown_card
from server.content.exit_props import (
    ARROW_PROP_ID,
    DOOR_PROP_ID,
    EXIT_PROP_RENDER_KINDS,
    STAIRS_PROP_ID,
)
from server.content.prop_assets import PROP_MODEL_PLACEHOLDER_PATH
from server.content.sounds import PROP_SOUND_KEYS, parse_sounds
from server.content.surface_props import SIGN_PROP_ID, WHITEBOARD_PROP_ID
from server.content.text_props import TEXT_PROP_ID, validate_text

if TYPE_CHECKING:
    from server.content.fx import EffectDefinition


PROPS_CONFIG_KEY = "CONFIG"
DEFAULT_PROP_PRICE = 5
FREE_PROPSET_SOURCES = frozenset({"base"})
PROP_RENDER_KINDS = frozenset({"model", "text", "sign", "whiteboard"}) | EXIT_PROP_RENDER_KINDS
# Gameplay fields owned by a prop definition. Authoring them on a room prop
# instance is rejected so every instance of the prop behaves identically.
MOVED_INSTANCE_PROP_FIELDS = frozenset({"activity", "behavior", "content", "cooldown", "recipes"})
# Tags that mark a prop as a container ("closed containers only": open
# shelves and bookshelves are excluded even though they carry `storage`).
# Props with an authored behavior keep it; the rule only fills in behavior
# for behavior-less container-like props.
CONTAINER_TAGS = frozenset({"storage", "cabinet", "wardrobe", "trashcan", "bin", "crate", "nightstand"})
CONTAINER_OPEN_TAGS = frozenset({"shelf", "bookshelf"})


@dataclass(frozen=True, slots=True)
class QuickAction:
    """A server-provided quick action template."""

    # Authored as [label, command, optional default]; default enables activation
    # on reselect. Command availability is filtered at runtime, not parsed here.
    label: str
    command: str
    default: bool = False


@dataclass(frozen=True, slots=True)
class PropStateDefinition:
    """A named mesh variant a prop instance can switch to at runtime."""

    name: str
    model_name: str
    model_path: Path
    model_missing: bool = False


@dataclass(frozen=True, slots=True)
class PropDefinition:
    """An immutable prop definition."""

    id: str
    label: str
    description: str
    model_name: str | None
    model_path: Path | None
    decorative: bool
    animation: str | None
    scale: float
    behavior: str | None = None
    content: tuple[str, ...] = ()
    cooldown: int | None = None
    recipes: tuple[str, ...] = ()
    activity: str | None = None
    one_per_room: bool = False
    # Default quick actions every placed instance receives. ``@self`` in a
    # command targets the concrete instance being serialized.
    default_actions: tuple[QuickAction, ...] = ()
    editor_scale_min: float = 0.25
    editor_scale_max: float = 4.0
    source: str = ""
    source_kind: str = "world"
    tags: tuple[str, ...] = ()
    price: int = DEFAULT_PROP_PRICE
    locked: bool = False
    hidden: bool = False
    requires_light: bool = False
    model_missing: bool = False
    # Set names select ordered lists of catalog effect ids, not gameplay effects.
    # This active_effect is the authored default; RoomService can override it per
    # room/instance in memory and broadcast room.prop.updated. Reduced motion
    # suppresses client rendering without changing the authoritative selection.
    effect_sets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    active_effect: str | None = None
    render_kind: str = "model"
    # Named mesh variants. This active_state is the authored starting state;
    # RoomService can override it per room/instance in memory and broadcast
    # room.prop.updated so clients reload the active model.
    states: dict[str, PropStateDefinition] = field(default_factory=dict)
    active_state: str | None = None
    # Half-extents in board percent at the definition's authored scale, used by
    # sprite-mode rooms to keep peeps off furniture.
    sprite_footprint: tuple[float, float] | None = None
    sounds: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PropInstanceDefinition:
    """A prop instance placed into a room."""

    # Instance scale multiplies the definition's already file-adjusted scale.
    # Behavior, activity, content, cooldown, and recipes live on the prop
    # definition; an instance only overrides placement, label, description,
    # custom quick actions, exit destination and finish, and surface recipes.
    id: str
    prop_id: str
    pos: tuple[float, float, float]
    rot: tuple[float, float, float]
    scale: float
    actions: tuple[QuickAction, ...]
    personal: bool
    animation: str | None
    draw_weight: dict[str, float] = field(default_factory=dict)
    only_missing: bool = False
    text: dict[str, str] | None = None
    sign_style: str | None = None
    surface: dict[str, object] | None = None
    sounds: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    label: str | None = None
    exit_to: str | None = None
    exit_style: dict[str, str] | None = None


def _load_text_recipe(
    raw_instance: dict[str, Any], render_kind: str, room_id: str, instance_id: str,
) -> dict[str, str] | None:
    context = f"Room '{room_id}' prop '{instance_id}' text"
    if render_kind != "text":
        if "text" in raw_instance:
            raise ContentError(f"{context}: Only text props may have a text recipe.")
        return None
    try:
        return validate_text(raw_instance.get("text"))
    except ValueError as exc:
        raise ContentError(f"{context}: {exc}") from exc


def builtin_prop_definitions() -> dict[str, PropDefinition]:
    """Register procedural props independently of authored model catalogs."""

    return {
        TEXT_PROP_ID: PropDefinition(
            id=TEXT_PROP_ID, label="Text", description="Custom three-dimensional text.",
            model_name=None, model_path=None, decorative=True, animation=None,
            scale=1.0, source="builtin", source_kind="builtin",
            tags=("text",), price=0, locked=False, render_kind="text",
        ),
        SIGN_PROP_ID: PropDefinition(
            id=SIGN_PROP_ID, label="Sign", description="An editable sign with a choice of finishes.",
            model_name=None, model_path=None, decorative=True, animation=None,
            scale=1.0, source="builtin", source_kind="builtin",
            tags=("sign", "editable"), price=0, locked=False, render_kind="sign",
        ),
        WHITEBOARD_PROP_ID: PropDefinition(
            id=WHITEBOARD_PROP_ID, label="Whiteboard",
            description="A shared whiteboard for notes and marker drawings.",
            model_name=None, model_path=None, decorative=True, animation=None,
            scale=1.0, activity="whiteboard", editor_scale_max=5.0, source="builtin", source_kind="builtin",
            tags=("whiteboard", "editable"), price=0, locked=False, render_kind="whiteboard",
        ),
        DOOR_PROP_ID: PropDefinition(
            id=DOOR_PROP_ID, label="Door", description="A simple door that can lead to a room exit.",
            model_name=None, model_path=None, decorative=False, animation=None,
            scale=1.0, source="builtin", source_kind="builtin",
            tags=("exit", "door"), price=0, locked=False, render_kind="door",
        ),
        ARROW_PROP_ID: PropDefinition(
            id=ARROW_PROP_ID, label="Arrow", description="A simple arrow that can lead to a room exit.",
            model_name=None, model_path=None, decorative=False, animation=None,
            scale=1.0, source="builtin", source_kind="builtin",
            tags=("exit", "arrow"), price=0, locked=False, render_kind="arrow",
        ),
        STAIRS_PROP_ID: PropDefinition(
            id=STAIRS_PROP_ID, label="Stairs", description="A simple set of stairs that can lead to a room exit.",
            model_name=None, model_path=None, decorative=False, animation=None,
            scale=1.0, source="builtin", source_kind="builtin",
            tags=("exit", "stairs"), price=0, locked=False, render_kind="stairs",
        ),
    }


def _load_draw_weight(raw_value: Any, prop_instance_id: str, card_ids: set[str]) -> dict[str, float]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ContentError(f"Prop '{prop_instance_id}' draw_weight must be a mapping.")
    draw_weight: dict[str, float] = {}
    for card_id, weight in raw_value.items():
        if not isinstance(card_id, str):
            raise ContentError(f"Prop '{prop_instance_id}' draw_weight references unknown card '{card_id}'.")
        if card_id not in card_ids:
            warn_unknown_card(f"Prop '{prop_instance_id}' draw_weight", card_id)
            continue
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or float(weight) < 0:
            raise ContentError(f"Prop '{prop_instance_id}' draw_weight for '{card_id}' must be a non-negative number.")
        draw_weight[card_id] = float(weight)
    return draw_weight


def _load_actions(raw_value: Any) -> tuple[QuickAction, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError("Actions must be a list.")
    actions: list[QuickAction] = []
    for entry in raw_value:
        if not isinstance(entry, list) or len(entry) not in (2, 3):
            raise ContentError("Each action must be a [label, command] or [label, command, default] list.")
        label, command = entry[0], entry[1]
        if not isinstance(label, str) or not isinstance(command, str):
            raise ContentError("Action label and command must be strings.")
        is_default = entry[2] if len(entry) == 3 else False
        if not isinstance(is_default, bool):
            raise ContentError("Action default flag must be a boolean.")
        actions.append(QuickAction(label=label.strip(), command=command.strip(), default=is_default))
    return tuple(actions)


def resolve_default_prop_actions(
    definition: PropDefinition, instance_id: str
) -> tuple[QuickAction, ...]:
    """Return a definition's default actions targeted at one placed instance."""

    return tuple(
        QuickAction(
            label=action.label,
            command=action.command.replace("@self", f"@prop:{instance_id}"),
            default=action.default,
        )
        for action in definition.default_actions
    )


def _load_vec3(raw_value: Any, label: str) -> tuple[float, float, float]:
    if raw_value is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise ContentError(f"{label} must be a 3-item list.")
    return (float(raw_value[0]), float(raw_value[1]), float(raw_value[2]))


def _load_sprite_footprint(raw_value: Any, prop_id: str) -> tuple[float, float] | None:
    """Read optional per-prop half-extents in board percent at authored scale."""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise ContentError(f"Prop '{prop_id}' sprite_footprint must be a 2-item list.")
    values: list[float] = []
    for raw_value_item in raw_value:
        if isinstance(raw_value_item, bool) or not isinstance(raw_value_item, (int, float)):
            raise ContentError(f"Prop '{prop_id}' sprite_footprint values must be numbers.")
        value = float(raw_value_item)
        if value <= 0:
            raise ContentError(f"Prop '{prop_id}' sprite_footprint values must be positive.")
        values.append(value)
    return (values[0], values[1])


def _load_animation(raw_value: Any, label: str) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ContentError(f"{label} must be a string.")
    text = raw_value.strip()
    return text or None


def _load_prop_states(
    raw_value: Any,
    props_file: Path,
    prop_id: str,
) -> dict[str, PropStateDefinition]:
    """Parse a prop's named mesh states: ``{state_name: model_file}``.

    Values may be a model filename directly or a mapping with a ``model`` key,
    leaving room for future per-state options without changing the shorthand.
    """

    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ContentError(f"Prop '{prop_id}' states must be a mapping of state names to models.")
    states: dict[str, PropStateDefinition] = {}
    for raw_name, raw_state in raw_value.items():
        state_name = str(raw_name).strip()
        if not state_name:
            raise ContentError(f"Prop '{prop_id}' contains an empty state name.")
        if isinstance(raw_state, str):
            model_name = raw_state.strip()
        elif isinstance(raw_state, dict):
            model_name = str(raw_state.get("model", "")).strip()
        else:
            raise ContentError(
                f"Prop '{prop_id}' state '{state_name}' must be a model filename "
                "or a mapping with a model."
            )
        if not model_name:
            raise ContentError(f"Prop '{prop_id}' state '{state_name}' is missing its model.")
        model_path = (props_file.parent / model_name).resolve()
        model_missing = not model_path.is_file()
        if model_missing:
            LOGGER.warning(
                "Prop '%s' state '%s' references missing model '%s'; using a placeholder.",
                prop_id,
                state_name,
                model_name,
            )
            model_path = PROP_MODEL_PLACEHOLDER_PATH
        states[state_name] = PropStateDefinition(
            name=state_name,
            model_name=model_name,
            model_path=model_path,
            model_missing=model_missing,
        )
    return states


def _load_active_state(
    raw_value: Any,
    states: dict[str, PropStateDefinition],
    prop_id: str,
) -> str | None:
    """Resolve the authored starting state, defaulting to the first declared one."""

    if not states:
        if raw_value is not None:
            raise ContentError(f"Prop '{prop_id}' declares active_state without any states.")
        return None
    if raw_value is None:
        return next(iter(states))
    if not isinstance(raw_value, str):
        raise ContentError(f"Prop '{prop_id}' active_state must be a string.")
    active_state = raw_value.strip()
    if active_state not in states:
        raise ContentError(
            f"Prop '{prop_id}' active_state '{active_state}' is not one of its states."
        )
    return active_state


def _load_effect_sets(raw_value: Any, label: str) -> dict[str, tuple[str, ...]]:
    """Parse a prop's named effect sets: ``{set_name: [effect_id, ...]}``.

    Empty mappings and empty set lists are valid: they represent a prop with no
    effects at all, or a named set that intentionally produces nothing.
    """

    if raw_value is None:
        return {}
    if isinstance(raw_value, list):
        raw_value = {"default": raw_value}
    if not isinstance(raw_value, dict):
        raise ContentError(f"{label} must be a mapping of set names to effect lists.")
    sets: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_effects in raw_value.items():
        set_name = str(raw_name).strip()
        if not set_name:
            raise ContentError(f"{label} contains an empty set name.")
        if not isinstance(raw_effects, list):
            raise ContentError(f"{label} set '{set_name}' must be a list of effect ids.")
        effect_ids: list[str] = []
        for raw_effect in raw_effects:
            effect_id = str(raw_effect).strip()
            if not effect_id:
                raise ContentError(f"{label} set '{set_name}' contains an empty effect id.")
            if effect_id not in effect_ids:
                effect_ids.append(effect_id)
        sets[set_name] = tuple(effect_ids)
    return sets


def _load_active_effect(raw_value: Any, effect_sets: dict[str, tuple[str, ...]], prop_id: str) -> str | None:
    """Resolve the default active set, defaulting to the first declared set."""

    if not effect_sets:
        if raw_value is not None:
            raise ContentError(f"Prop '{prop_id}' declares active_effect without any effects.")
        return None
    if raw_value is None:
        return next(iter(effect_sets))
    if not isinstance(raw_value, str):
        raise ContentError(f"Prop '{prop_id}' active_effect must be a string.")
    active = raw_value.strip()
    if active not in effect_sets:
        raise ContentError(f"Prop '{prop_id}' active_effect '{active}' is not one of its effect sets.")
    return active


def _load_prop_render_kind(raw_value: Any, prop_id: str) -> str:
    if raw_value is None:
        return "model"
    if not isinstance(raw_value, str):
        raise ContentError(f"Prop '{prop_id}' render_kind must be a string.")
    render_kind = raw_value.strip()
    if render_kind not in PROP_RENDER_KINDS:
        raise ContentError(
            f"Prop '{prop_id}' has unknown render_kind '{render_kind}'. "
            f"Expected one of {', '.join(sorted(PROP_RENDER_KINDS))}."
        )
    return render_kind


def _load_optional_prop_name(raw_value: Any, prop_id: str, field_name: str) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ContentError(f"Prop '{prop_id}' {field_name} must be a string.")
    return raw_value.strip() or None


def _load_identifier_list(raw_value: Any, prop_id: str, field_name: str) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError(f"Prop '{prop_id}' {field_name} must be a list.")
    values: list[str] = []
    for entry in raw_value:
        if not isinstance(entry, str) or not entry.strip():
            raise ContentError(f"Prop '{prop_id}' {field_name} entries must be non-empty strings.")
        value = entry.strip()
        if value not in values:
            values.append(value)
    return tuple(values)


def _load_prop_cooldown(raw_value: Any, prop_id: str) -> int | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ContentError(f"Prop '{prop_id}' has an invalid cooldown {raw_value!r}.")
    cooldown = int(raw_value)
    if cooldown < 0:
        raise ContentError(f"Prop '{prop_id}' has an invalid cooldown {raw_value!r}.")
    return cooldown


def load_props_scale_adjust(raw_config: Any, path: Path) -> float:
    """Read the reserved CONFIG block's optional file-wide scale multiplier."""

    # CONFIG is never a prop. scale_adjust defaults to 1.0 for every world,
    # propset, or mod props.yaml independently; other CONFIG keys are ignored.
    if raw_config is None:
        return 1.0
    if not isinstance(raw_config, dict):
        raise ContentError(f"{path} CONFIG must be a mapping.")
    raw_adjust = raw_config.get("scale_adjust", 1.0)
    if isinstance(raw_adjust, bool) or not isinstance(raw_adjust, (int, float)) or float(raw_adjust) <= 0:
        raise ContentError(f"{path} CONFIG scale_adjust has an invalid value {raw_adjust!r}.")
    return float(raw_adjust)


def load_prop_definition(
    prop_id: str,
    raw_prop: Mapping[str, Any],
    *,
    props_file: Path,
    source: str,
    source_kind: str = "world",
    scale_adjust: float = 1.0,
    known_sounds: frozenset[str] | None = None,
) -> PropDefinition:
    """Validate and build one prop definition from a raw YAML mapping.

    Models resolve relative to the props file's directory, and ``scale`` is
    multiplied by the file-level ``scale_adjust``. Missing models are replaced by
    the shared placeholder; they warn rather than aborting a world load. Shared by
    the content loader and the Prop Editor so both enforce identical rules.
    """

    if not isinstance(prop_id, str) or not isinstance(raw_prop, dict):
        raise ContentError(f"{props_file} contains an invalid prop entry.")
    if prop_id.startswith("builtin:"):
        raise ContentError(f"Prop id '{prop_id}' is reserved for built-in procedural props.")
    render_kind = _load_prop_render_kind(raw_prop.get("render_kind"), prop_id)
    states = _load_prop_states(raw_prop.get("states"), props_file, prop_id)
    if states and render_kind != "model":
        raise ContentError(f"Prop '{prop_id}' render_kind '{render_kind}' must not declare mesh states.")
    raw_active_state = raw_prop.get("active_state", raw_prop.get("default_state"))
    active_state = _load_active_state(raw_active_state, states, prop_id)
    raw_model = str(raw_prop.get("model", "")).strip()
    if render_kind != "model":
        if raw_model:
            raise ContentError(f"Prop '{prop_id}' render_kind '{render_kind}' must not define a model.")
        model_name = None
        model_path = None
        model_missing = False
    else:
        model_name = raw_model
        if not model_name:
            if not states:
                raise ContentError(f"Prop '{prop_id}' is missing its model.")
            active_definition = states[active_state] if active_state is not None else next(iter(states.values()))
            model_name = active_definition.model_name
            model_path = active_definition.model_path
            model_missing = active_definition.model_missing
        else:
            model_path = (props_file.parent / model_name).resolve()
            model_missing = not model_path.is_file()
            if model_missing:
                LOGGER.warning(
                    "Prop '%s' references missing model '%s'; using a placeholder.",
                    prop_id,
                    model_name,
                )
                model_path = PROP_MODEL_PLACEHOLDER_PATH
    raw_scale = raw_prop.get("scale", 1.0)
    if isinstance(raw_scale, bool) or not isinstance(raw_scale, (int, float)) or float(raw_scale) <= 0:
        raise ContentError(f"Prop '{prop_id}' has an invalid scale {raw_scale!r}.")
    scale = float(raw_scale) * scale_adjust
    decorative = bool(raw_prop.get("decorative", False))
    editor_scale_min = float(raw_prop.get("editor_scale_min", 0.25))
    editor_scale_max = float(raw_prop.get("editor_scale_max", 4.0))
    if editor_scale_min <= 0 or editor_scale_max < editor_scale_min:
        raise ContentError(f"Prop '{prop_id}' has invalid editor scale bounds.")
    raw_tags = raw_prop.get("tags", []) or []
    if not isinstance(raw_tags, list):
        raise ContentError(f"Prop '{prop_id}' tags must be a list.")
    tags: list[str] = []
    for raw_tag in raw_tags:
        tag = str(raw_tag).strip().lower()
        if not tag:
            raise ContentError(f"Prop '{prop_id}' has an empty tag.")
        if tag not in tags:
            tags.append(tag)
    raw_price = raw_prop.get("price", DEFAULT_PROP_PRICE)
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)) or int(raw_price) < 0:
        raise ContentError(f"Prop '{prop_id}' has an invalid price {raw_price!r}.")
    price = int(raw_price)
    if "locked" in raw_prop:
        locked = bool(raw_prop.get("locked"))
    else:
        locked = decorative and source_kind == "propset" and source not in FREE_PROPSET_SOURCES
    hidden = bool(raw_prop.get("hidden", False))
    requires_light = bool(raw_prop.get("requires_light", False))
    behavior = _load_optional_prop_name(raw_prop.get("behavior"), prop_id, "behavior")
    if behavior is None:
        tag_set = set(tags)
        if tag_set & CONTAINER_TAGS and not tag_set & CONTAINER_OPEN_TAGS:
            behavior = "container"
    activity = _load_optional_prop_name(raw_prop.get("activity"), prop_id, "activity")
    content = _load_identifier_list(raw_prop.get("content"), prop_id, "content")
    recipes = _load_identifier_list(raw_prop.get("recipes"), prop_id, "recipes")
    cooldown = _load_prop_cooldown(raw_prop.get("cooldown"), prop_id)
    one_per_room = bool(raw_prop.get("one_per_room", False))
    default_actions = _load_actions(raw_prop.get("default_actions"))
    if behavior == "container" and not any(
        action.command.strip() == ".open" or action.command.strip().lower().startswith(".open ")
        for action in default_actions
    ):
        default_actions = (*default_actions, QuickAction(label="Open", command=".open @self"))
    effect_sets = _load_effect_sets(raw_prop.get("effects"), f"Prop '{prop_id}' effects")
    active_effect = _load_active_effect(raw_prop.get("active_effect"), effect_sets, prop_id)
    sprite_footprint = _load_sprite_footprint(raw_prop.get("sprite_footprint"), prop_id)
    sounds = parse_sounds(
        raw_prop.get("sounds"),
        f"Prop '{prop_id}'",
        PROP_SOUND_KEYS,
        known_sounds=known_sounds,
    )
    return PropDefinition(
        id=prop_id,
        label=str(raw_prop.get("label", "")).strip(),
        description=str(raw_prop.get("description", "")).strip(),
        model_name=model_name,
        model_path=model_path,
        model_missing=model_missing,
        decorative=decorative,
        animation=_load_animation(raw_prop.get("animation"), f"Prop '{prop_id}' animation"),
        scale=scale,
        behavior=behavior,
        content=content,
        cooldown=cooldown,
        recipes=recipes,
        activity=activity,
        one_per_room=one_per_room,
        default_actions=default_actions,
        editor_scale_min=editor_scale_min,
        editor_scale_max=editor_scale_max,
        source=source,
        source_kind=source_kind,
        tags=tuple(tags),
        price=price,
        locked=locked,
        hidden=hidden,
        requires_light=requires_light,
        effect_sets=effect_sets,
        active_effect=active_effect,
        render_kind=render_kind,
        states=states,
        active_state=active_state,
        sprite_footprint=sprite_footprint,
        sounds=sounds,
    )


def _load_props_from_file(
    path: Path,
    source: str,
    source_kind: str = "world",
    *,
    known_sounds: frozenset[str] | None = None,
) -> dict[str, PropDefinition]:
    """Load prop definitions from one props.yaml, resolving models beside it."""

    props_payload = require_mapping(load_yaml_file(path), path)
    scale_adjust = load_props_scale_adjust(props_payload.get(PROPS_CONFIG_KEY), path)
    props: dict[str, PropDefinition] = {}
    for prop_id, raw_prop in props_payload.items():
        if prop_id == PROPS_CONFIG_KEY:
            continue
        props[prop_id] = load_prop_definition(
            prop_id,
            raw_prop,
            props_file=path,
            source=source,
            source_kind=source_kind,
            scale_adjust=scale_adjust,
            known_sounds=known_sounds,
        )
    return props


def _validate_prop_effects(props: Mapping[str, PropDefinition], effects: Mapping[str, EffectDefinition]) -> None:
    """Reject props that reference effect ids absent from the loaded catalog."""

    for definition in props.values():
        for set_name, effect_ids in definition.effect_sets.items():
            for effect_id in effect_ids:
                if effect_id not in effects:
                    raise ContentError(
                        f"Prop '{definition.id}' effect set '{set_name}' references unknown effect '{effect_id}'."
                    )


def load_propset(
    propset_path: Path,
    effects: Mapping[str, EffectDefinition] | None = None,
) -> dict[str, PropDefinition]:
    """Load a shared propset directory's ``props.yaml`` definitions."""

    props_file = propset_path / "props.yaml"
    if not props_file.is_file():
        raise ContentError(f"Propset is missing props.yaml: {propset_path}")
    props = _load_props_from_file(props_file, propset_path.name, source_kind="propset")
    if effects is not None:
        _validate_prop_effects(props, effects)
    return props
