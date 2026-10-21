"""World-authored interactive games placed inside rooms."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from server.content.common import ContentError

if TYPE_CHECKING:
    from server.content.worlds import PropDefinition, PropInstanceDefinition


MAX_GAME_CONFIG_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class GameModelDefinition:
    """A named model a game renderer can display."""

    name: str
    prop_id: str


@dataclass(frozen=True, slots=True)
class RoomGameDefinition:
    """A generic game envelope whose renderer and state stay world-owned.

    The core validates the controller, static assets, model references, and
    reset powers. It deliberately does not interpret ``config``; renderers
    decide what a grid, lane, table, or other board shape means.
    """

    kind: str
    controller: str
    renderer: str
    reset_powers: tuple[str, ...]
    assets: dict[str, str]
    models: dict[str, GameModelDefinition]
    effect_sets: dict[str, tuple[str, ...]]
    config: dict[str, object]


def _load_asset_map(
    raw_assets: Any,
    *,
    world_root: Path,
    room_id: str,
) -> dict[str, str]:
    if raw_assets is None:
        return {}
    if not isinstance(raw_assets, dict):
        raise ContentError(f"Room '{room_id}' game assets must be a mapping.")
    assets: dict[str, str] = {}
    world_root = world_root.resolve()
    for raw_name, raw_path in raw_assets.items():
        name = str(raw_name).strip()
        relative = str(raw_path).strip()
        if not name or not relative:
            raise ContentError(f"Room '{room_id}' game has an invalid asset entry.")
        resolved = (world_root / relative).resolve()
        if resolved != world_root and world_root not in resolved.parents:
            raise ContentError(f"Room '{room_id}' game asset '{name}' escapes the world directory.")
        if not resolved.is_file():
            raise ContentError(f"Room '{room_id}' game asset '{name}' references missing file '{relative}'.")
        assets[name] = relative.replace("\\", "/")
    return assets


def _load_model_map(
    raw_models: Any,
    *,
    room_id: str,
    props: Mapping[str, PropDefinition],
) -> dict[str, GameModelDefinition]:
    if raw_models is None:
        return {}
    if not isinstance(raw_models, dict):
        raise ContentError(f"Room '{room_id}' game models must be a mapping.")
    models: dict[str, GameModelDefinition] = {}
    for raw_name, raw_prop_id in raw_models.items():
        name = str(raw_name).strip()
        prop_id = str(raw_prop_id).strip()
        if not name or not prop_id:
            raise ContentError(f"Room '{room_id}' game has an invalid model entry.")
        definition = props.get(prop_id)
        if definition is None:
            raise ContentError(f"Room '{room_id}' game model '{name}' references unknown prop '{prop_id}'.")
        if definition.render_kind != "model" or definition.model_path is None:
            raise ContentError(f"Room '{room_id}' game model '{name}' must reference a model prop.")
        if definition.hidden:
            raise ContentError(f"Room '{room_id}' game model '{name}' references a hidden prop.")
        models[name] = GameModelDefinition(name=name, prop_id=prop_id)
    return models


def _load_effect_sets(
    raw_effects: Any,
    *,
    room_id: str,
    effects: Mapping[str, object],
) -> dict[str, tuple[str, ...]]:
    if raw_effects is None:
        return {}
    if not isinstance(raw_effects, dict):
        raise ContentError(f"Room '{room_id}' game effects must be a mapping.")
    effect_sets: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_ids in raw_effects.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_ids, list):
            raise ContentError(f"Room '{room_id}' game has an invalid effect set.")
        effect_ids: list[str] = []
        for raw_id in raw_ids:
            effect_id = str(raw_id).strip()
            if not effect_id:
                raise ContentError(f"Room '{room_id}' game effect set '{name}' has an empty id.")
            if effect_id not in effects:
                raise ContentError(
                    f"Room '{room_id}' game effect set '{name}' references unknown effect '{effect_id}'."
                )
            if effect_id not in effect_ids:
                effect_ids.append(effect_id)
        effect_sets[name] = tuple(effect_ids)
    return effect_sets


def _load_config(raw_config: Any, *, room_id: str) -> dict[str, object]:
    if raw_config is None:
        return {}
    if not isinstance(raw_config, dict):
        raise ContentError(f"Room '{room_id}' game config must be a mapping.")
    try:
        encoded = json.dumps(raw_config, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ContentError(f"Room '{room_id}' game config must be JSON-serializable.") from exc
    if len(encoded.encode("utf-8")) > MAX_GAME_CONFIG_BYTES:
        raise ContentError(
            f"Room '{room_id}' game config exceeds the {MAX_GAME_CONFIG_BYTES}-byte limit."
        )
    return dict(raw_config)


def load_room_game(
    raw_game: Any,
    *,
    world_root: Path,
    room_id: str,
    room_props: Mapping[str, PropInstanceDefinition],
    props: Mapping[str, PropDefinition],
    effects: Mapping[str, object],
    power_names: tuple[str, ...],
) -> RoomGameDefinition | None:
    """Validate a room's optional generic game envelope."""

    if raw_game is None:
        return None
    if not isinstance(raw_game, dict):
        raise ContentError(f"Room '{room_id}' game must be a mapping.")
    kind = str(raw_game.get("kind", "")).strip()
    if not kind:
        raise ContentError(f"Room '{room_id}' game is missing kind.")
    renderer = str(raw_game.get("renderer", "")).strip()
    if not renderer:
        raise ContentError(f"Room '{room_id}' game is missing renderer.")
    if len(renderer) > 64:
        raise ContentError(f"Room '{room_id}' game renderer name is too long.")
    controller = str(raw_game.get("controller", "")).strip()
    instance = room_props.get(controller)
    if instance is None:
        raise ContentError(f"Room '{room_id}' game controller '{controller}' is not a prop in the room.")
    if not instance.behavior:
        raise ContentError(f"Room '{room_id}' game controller '{controller}' has no behavior script.")
    raw_powers = raw_game.get("reset_powers", list(power_names))
    if not isinstance(raw_powers, list):
        raise ContentError(f"Room '{room_id}' game reset_powers must be a list.")
    reset_powers: list[str] = []
    for raw_power in raw_powers:
        power = str(raw_power).strip()
        if power not in power_names:
            raise ContentError(f"Room '{room_id}' game reset power '{power}' is unknown.")
        if power not in reset_powers:
            reset_powers.append(power)
    return RoomGameDefinition(
        kind=kind,
        controller=controller,
        renderer=renderer,
        reset_powers=tuple(reset_powers),
        assets=_load_asset_map(raw_game.get("assets"), world_root=world_root, room_id=room_id),
        models=_load_model_map(raw_game.get("models"), room_id=room_id, props=props),
        effect_sets=_load_effect_sets(raw_game.get("effects"), room_id=room_id, effects=effects),
        config=_load_config(raw_game.get("config"), room_id=room_id),
    )
