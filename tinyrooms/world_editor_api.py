"""World-editor REST API — enabled only when --feature world-editor is active."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4
import re

import yaml
from flask import Blueprint, jsonify, request, send_from_directory

from . import db, icons
from .prop import Prop
from .room import Room, Way
from .world import active_world, serialize_prop_library

blueprint = Blueprint("world_editor", __name__)

_STATIC_FOLDER = Path(__file__).parent.parent / "app"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _feature_enabled() -> bool:
    from . import server  # noqa: PLC0415
    return server.feature_enabled("world-editor")


def _require_user() -> str:
    from . import server  # noqa: PLC0415
    return server._require_rest_user()


def _prop_repo():
    from . import server  # noqa: PLC0415
    return server._prop_repo(force_reindex=False)


def _err(msg: str, code: int, **extra):
    payload = {"ok": False, "error": msg}
    payload.update(extra)
    return jsonify(payload), code


def _guard():
    if not _feature_enabled():
        return _err("world-editor feature disabled", 404)
    return None


def _coerce_int(value, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _normalize_room_id(room_id: str) -> str:
    value = str(room_id or "").strip()
    if not value:
        raise ValueError("room_id is required")
    if not _ID_RE.fullmatch(value):
        raise ValueError("room_id must use snake_case letters, digits, or underscores")
    return value


def _normalize_way_id(way_id: str) -> str:
    value = str(way_id or "").strip()
    if not value:
        raise ValueError("way_id is required")
    if not _ID_RE.fullmatch(value):
        raise ValueError("way_id must use snake_case letters, digits, or underscores")
    return value


def _normalize_way_refs(raw_value) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        raise ValueError("ways must be a string or list")
    out = []
    seen = set()
    for item in values:
        way_id = _normalize_way_id(item)
        if way_id not in seen:
            out.append(way_id)
            seen.add(way_id)
    return out


def _room_way_ids(room) -> list[str]:
    return _normalize_way_refs(room.info.get("ways", []))


def _set_room_way_ids(room, way_ids: list[str]) -> None:
    room.info["ways"] = way_ids[0] if len(way_ids) == 1 else list(way_ids)
    room.ways = {way_id: active_world().ways[way_id] for way_id in way_ids if way_id in active_world().ways}


def _normalized_stage(stage: dict | None, existing: dict | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    data = dict(stage or {})
    stage_type = str(data.get("type", base.get("type", "basic")) or "basic").strip().lower()
    if stage_type not in {"basic", "standard"}:
        raise ValueError("stage.type must be 'basic' or 'standard'")
    background_mode = str(
        data.get("background_mode", base.get("background_mode", "tile")) or "tile"
    ).strip().lower()
    if background_mode not in {"tile", "stretch"}:
        raise ValueError("stage.background_mode must be 'tile' or 'stretch'")
    out = {
        "type": stage_type,
        "width": _coerce_int(data.get("width", base.get("width", 400)), 400),
        "background_mode": background_mode,
    }
    if stage_type == "basic":
        out["height"] = _coerce_int(data.get("height", base.get("height", 300)), 300)
    else:
        out["bg_height"] = _coerce_int(data.get("bg_height", base.get("bg_height", 200)), 200)
        out["floor_height"] = _coerce_int(data.get("floor_height", base.get("floor_height", 100)), 100)
        floor_image = str(data.get("floor_image", base.get("floor_image", "")) or "").strip()
        if floor_image:
            out["floor_image"] = floor_image
    theme = str(data.get("theme", base.get("theme", "")) or "").strip()
    if theme:
        out["theme"] = theme
    bounds = data.get("bounds", base.get("bounds", {}))
    if isinstance(bounds, dict) and bounds:
        out["bounds"] = dict(bounds)
    return out


def _resolve_asset_url(asset_path: str) -> str:
    path = str(asset_path or "").strip()
    if not path:
        return ""
    if path.startswith("/") or path.startswith("http://") or path.startswith("https://"):
        return path
    return f"/world/{path}"


def _serialize_room(room) -> dict[str, Any]:
    stage = _normalized_stage(room.info.get("stage", {}), room.info.get("stage", {}))
    background = str(room.info.get("image") or room.info.get("img") or "").strip()
    description = room.description_override if room.description_override is not None else room.info.get("description", "")
    props = sorted(room.props.values(), key=lambda prop: (int(getattr(prop, "layer", 0)), int(getattr(prop, "z_order", 0)), prop.prop_instance_id))
    return {
        "room_id": room.room_id,
        "label": room.label(),
        "description": description,
        "owner_id": room.owner_id or "",
        "background": background,
        "background_url": _resolve_asset_url(background),
        "stage": stage,
        "ways": _room_way_ids(room),
        "props": [room._serialize_prop(prop) for prop in props],
    }


def _serialize_way(world, way_id: str, way) -> dict[str, Any]:
    target_room_id = str(way.info.get("to", "") or "").strip()
    target_room = world.rooms.get(target_room_id)
    referenced_by = sorted(room_id for room_id, room in world.rooms.items() if way_id in _room_way_ids(room))
    return {
        "way_id": way_id,
        "label": str(way.label or "").strip(),
        "to_room_id": target_room_id,
        "to_room_label": target_room.label() if target_room is not None else "",
        "from_room_ids": referenced_by,
    }


def _server_images_root() -> Path:
    return Path(__file__).parent.parent / "data" / "images"


def _list_available_images(world_root: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append(scope: str, stored_path: str, file_path: Path) -> None:
        normalized_path = stored_path.replace("\\", "/")
        if normalized_path in seen:
            return
        seen.add(normalized_path)
        items.append(
            {
                "scope": scope,
                "path": normalized_path,
                "name": file_path.name,
                "label": normalized_path,
                "url": _resolve_asset_url(normalized_path),
            }
        )

    if world_root.exists():
        for entry in sorted(world_root.iterdir(), key=lambda item: item.as_posix()):
            if entry.is_file() and entry.suffix.lower() in _IMAGE_EXTS:
                rel = entry.relative_to(world_root).as_posix()
                _append("world", rel, entry)
        world_images_dir = world_root / "images"
        if world_images_dir.exists():
            for entry in sorted(world_images_dir.rglob("*"), key=lambda item: item.as_posix()):
                if entry.is_file() and entry.suffix.lower() in _IMAGE_EXTS:
                    rel = entry.relative_to(world_root).as_posix()
                    _append("world", rel, entry)

    server_root = _server_images_root()
    if server_root.exists():
        for entry in sorted(server_root.rglob("*"), key=lambda item: item.as_posix()):
            if entry.is_file() and entry.suffix.lower() in _IMAGE_EXTS:
                rel = entry.relative_to(server_root).as_posix()
                _append("server", f"/server-images/{rel}", entry)

    return items


def _rooms_dir(world_root: Path) -> Path:
    return world_root / "rooms"


def _load_yaml_doc(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"rooms yaml must contain a mapping: {path.name}")
    return loaded


def _rooms_yaml_files(world_root: Path) -> list[Path]:
    return sorted(_rooms_dir(world_root).glob("*.yaml"))


def _find_definition_file(world_root: Path, entity_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    for yaml_file in _rooms_yaml_files(world_root):
        doc = _load_yaml_doc(yaml_file)
        if entity_id in doc:
            return yaml_file, doc
    return None, None


def _default_rooms_file(world_root: Path) -> Path:
    preferred = _rooms_dir(world_root) / "rooms.yaml"
    if preferred.exists():
        return preferred
    return _rooms_dir(world_root) / "world-editor.yaml"


def _write_yaml_doc(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _persist_definition(world_root: Path, entity_id: str, payload: dict[str, Any]) -> None:
    yaml_file, doc = _find_definition_file(world_root, entity_id)
    if yaml_file is None or doc is None:
        yaml_file = _default_rooms_file(world_root)
        doc = _load_yaml_doc(yaml_file)
    doc[entity_id] = payload
    _write_yaml_doc(yaml_file, doc)


def _delete_definition(world_root: Path, entity_id: str) -> None:
    yaml_file, doc = _find_definition_file(world_root, entity_id)
    if yaml_file is None or doc is None or entity_id not in doc:
        return
    del doc[entity_id]
    _write_yaml_doc(yaml_file, doc)


def _clone_room_props(room) -> list[dict[str, Any]]:
    return [room._serialize_prop(prop) for prop in room.props.values()]


def _normalize_room_payload(body: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    info = deepcopy(existing or {})
    info["type"] = "room"
    info["label"] = str(body.get("label", info.get("label", "")) or "").strip()
    info["description"] = str(body.get("description", info.get("description", "")) or "").strip()
    owner_id = str(body.get("owner_id", info.get("owner_id", "")) or "").strip()
    if owner_id:
        info["owner_id"] = owner_id
    else:
        info.pop("owner_id", None)
    background = str(body.get("background", body.get("image", info.get("image", info.get("img", "")))) or "").strip()
    if background:
        info["image"] = background
    else:
        info.pop("image", None)
    info.pop("img", None)
    stage_body = body["stage"] if "stage" in body else info.get("stage", {})
    info["stage"] = _normalized_stage(stage_body, existing=info.get("stage", {}))
    if "ways" in body:
        way_ids = _normalize_way_refs(body.get("ways"))
        if way_ids:
            info["ways"] = way_ids[0] if len(way_ids) == 1 else way_ids
        else:
            info.pop("ways", None)
    return info


def _build_room_props(room, raw_props, allowed_way_ids: set[str] | None = None) -> tuple[dict[str, Prop], int]:
    world = active_world()
    if raw_props is None:
        props = {}
        for prop_instance_id, prop in room.props.items():
            if allowed_way_ids is not None and prop.metadata.get("exit_way_id") not in allowed_way_ids:
                prop.metadata.pop("exit_way_id", None)
            props[prop_instance_id] = prop
        max_z = max([10, *[int(getattr(prop, "z_order", 0)) for prop in props.values()]])
        return props, max_z
    if not isinstance(raw_props, list):
        raise ValueError("props must be a list")
    orientation_values = {"front", "back", "left", "right"}
    next_props: dict[str, Prop] = {}
    seen_ids: set[str] = set()
    max_z = 10
    for idx, raw_prop in enumerate(raw_props):
        if not isinstance(raw_prop, dict):
            raise ValueError("invalid prop entry")
        prop_id = str(raw_prop.get("prop_id", "")).strip()
        if not prop_id:
            raise ValueError("prop_id is required")
        if prop_id not in world.prop_defs:
            raise ValueError(f"unknown prop_id '{prop_id}'")
        prop_instance_id = str(raw_prop.get("prop_instance_id", "")).strip() or f"{room.room_id}-{prop_id}-{uuid4().hex[:8]}"
        if prop_instance_id in seen_ids:
            raise ValueError("duplicate prop_instance_id in payload")
        seen_ids.add(prop_instance_id)
        x = int(raw_prop.get("x", raw_prop.get("position", {}).get("x", 0)))
        y = int(raw_prop.get("y", raw_prop.get("position", {}).get("y", 0)))
        orientation = str(raw_prop.get("orientation", raw_prop.get("position", {}).get("orientation", "front")) or "front")
        if orientation not in orientation_values:
            raise ValueError(f"invalid orientation '{orientation}'")
        layer = int(raw_prop.get("layer", raw_prop.get("position", {}).get("layer", 0)))
        z_order = int(raw_prop.get("z_order", raw_prop.get("position", {}).get("z_order", idx + 11)))
        merged_info = dict(world.prop_defs[prop_id])
        merged_info.update(
            {
                "x": x,
                "y": y,
                "orientation": orientation,
                "layer": layer,
                "z_order": z_order,
            }
        )
        prop = Prop(prop_instance_id, prop_id, merged_info, room.room_id)
        prop._display_assets = icons._build_prop_display_assets(prop_id, _prop_repo())
        exit_way_id = str(raw_prop.get("exit_way_id") or raw_prop.get("metadata", {}).get("exit_way_id") or "").strip()
        if exit_way_id:
            valid_way_ids = allowed_way_ids if allowed_way_ids is not None else set(room.ways.keys())
            if exit_way_id not in valid_way_ids:
                raise ValueError(f"unknown exit way '{exit_way_id}'")
            prop.metadata["exit_way_id"] = exit_way_id
        next_props[prop.prop_instance_id] = prop
        max_z = max(max_z, z_order)
    return next_props, max_z


def _broadcast_room_updates(room, *, header: bool = False, stage: bool = False, exits: bool = False) -> None:
    for room_user in room.users.values():
        if header:
            room.send_header_view(room_user)
        if stage:
            room.send_room_stage_view(room_user)
        if exits:
            room.send_room_exits_view(room_user)


def _state_payload(username: str) -> dict[str, Any]:
    world = active_world()
    return {
        "ok": True,
        "world_id": world.ws_id,
        "world_label": str(world.info.get("label", world.ws_id) or world.ws_id),
        "username": username,
        "rooms": [_serialize_room(world.rooms[room_id]) for room_id in sorted(world.rooms.keys())],
        "ways": [_serialize_way(world, way_id, world.ways[way_id]) for way_id in sorted(world.ways.keys())],
        "images": _list_available_images(Path(world.root_path)),
        "prop_library": serialize_prop_library(world),
    }


@blueprint.route("/world-editor")
def world_editor_page():
    if g := _guard():
        return g
    return send_from_directory(str(_STATIC_FOLDER), "world-editor.html")


@blueprint.route("/api/world-editor/state")
def get_state():
    if g := _guard():
        return g
    try:
        username = _require_user()
        return jsonify(_state_payload(username))
    except PermissionError as exc:
        return _err(str(exc), 401)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return _err(f"internal error: {exc}", 500)

@blueprint.route("/api/world-editor/images")
def list_images():
    if g := _guard():
        return g
    try:
        _require_user()
        world = active_world()
        return jsonify({"ok": True, "images": _list_available_images(Path(world.root_path))})
    except PermissionError as exc:
        return _err(str(exc), 401)


@blueprint.route("/api/world-editor/images", methods=["POST"])
def upload_images():
    if g := _guard():
        return g
    try:
        _require_user()
    except PermissionError as exc:
        return _err(str(exc), 401)
    return _err("world-editor image upload is not supported", 405)


@blueprint.route("/api/world-editor/rooms", methods=["POST"])
def create_room():
    if g := _guard():
        return g
    try:
        _require_user()
        body = request.json or {}
        world = active_world()
        room_id = _normalize_room_id(body.get("room_id", ""))
        if room_id in world.rooms or room_id in world.ways:
            return _err("room_id already exists", 409)

        copy_from_id = str(body.get("copy_from", "") or "").strip()
        existing_info = None
        raw_props = body.get("props")
        if copy_from_id:
            source_room = world.rooms.get(copy_from_id)
            if source_room is None:
                return _err("copy_from room not found", 404)
            existing_info = deepcopy(source_room.info)
            existing_info.pop("ways", None)
            if raw_props is None:
                raw_props = _clone_room_props(source_room)

        room_info = _normalize_room_payload(body, existing=existing_info)
        room = Room(room_id, room_info, room_info.get("owner_id", ""))
        allowed_way_ids = set(_normalize_way_refs(room_info.get("ways", [])))
        unknown_way_ids = sorted(way_id for way_id in allowed_way_ids if way_id not in world.ways)
        if unknown_way_ids:
            return _err("unknown way id referenced by room", 400, way_ids=unknown_way_ids)
        room.ways = {way_id: world.ways[way_id] for way_id in allowed_way_ids if way_id in world.ways}
        props, max_z = _build_room_props(room, raw_props, allowed_way_ids=allowed_way_ids)
        room.props = props
        room._z_counter = max(10, max_z)
        world.rooms[room_id] = room
        world.room_defs[room_id] = room_info
        _persist_definition(Path(world.root_path), room_id, room_info)
        world.save_state(world.ws_id)
        return jsonify({"ok": True, "room": _serialize_room(room)}), 201
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)


@blueprint.route("/api/world-editor/rooms/<room_id>", methods=["PUT"])
def update_room(room_id):
    if g := _guard():
        return g
    try:
        _require_user()
        body = request.json or {}
        world = active_world()
        room_id = _normalize_room_id(room_id)
        room = world.rooms.get(room_id)
        if room is None:
            return _err("room not found", 404)

        room_info = _normalize_room_payload(body, existing=room.info)
        room.info = room_info
        room.owner_id = room_info.get("owner_id", "")
        room.label_override = None
        room.description_override = None
        allowed_way_ids = set(_normalize_way_refs(room_info.get("ways", [])))
        props, max_z = _build_room_props(room, body.get("props"), allowed_way_ids=allowed_way_ids)
        room.props = props
        room._z_counter = max(10, max_z)
        room.ways = {way_id: world.ways[way_id] for way_id in allowed_way_ids if way_id in world.ways}
        world.room_defs[room_id] = room_info
        _persist_definition(Path(world.root_path), room_id, room_info)
        world.save_state(world.ws_id)
        _broadcast_room_updates(room, header=True, stage=True, exits=True)
        return jsonify({"ok": True, "room": _serialize_room(room)})
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)


@blueprint.route("/api/world-editor/rooms/<room_id>", methods=["DELETE"])
def delete_room(room_id):
    if g := _guard():
        return g
    try:
        _require_user()
        world = active_world()
        room_id = _normalize_room_id(room_id)
        if room_id == "DEFAULT_ROOM":
            return _err("DEFAULT_ROOM cannot be deleted", 409)
        room = world.rooms.get(room_id)
        if room is None:
            return _err("room not found", 404)
        if room.users or room.peeps:
            return _err("cannot delete a room with connected users", 409)
        if room.objs:
            return _err("cannot delete a room that still contains objects", 409)
        related_ways = sorted(
            way_id
            for way_id, way in world.ways.items()
            if way.info.get("to") == room_id or way_id in _room_way_ids(room)
        )
        if related_ways:
            return _err("cannot delete a room while ways still reference it", 409, way_ids=related_ways)

        del world.rooms[room_id]
        world.room_defs.pop(room_id, None)
        _delete_definition(Path(world.root_path), room_id)
        with db.get_worldstate_connection(world.ws_id) as wsdb:
            db.delete_room_data(wsdb, room_id)
        return jsonify({"ok": True})
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)


@blueprint.route("/api/world-editor/ways", methods=["POST"])
def create_way():
    if g := _guard():
        return g
    try:
        _require_user()
        body = request.json or {}
        world = active_world()
        way_id = _normalize_way_id(body.get("way_id", ""))
        from_room_id = _normalize_room_id(body.get("from_room_id", ""))
        to_room_id = _normalize_room_id(body.get("to_room_id", ""))
        if way_id in world.ways or way_id in world.rooms:
            return _err("way_id already exists", 409)
        source_room = world.rooms.get(from_room_id)
        target_room = world.rooms.get(to_room_id)
        if source_room is None or target_room is None:
            return _err("from_room_id and to_room_id must exist", 404)

        created_way_ids = []
        for create_spec in [
            {
                "way_id": way_id,
                "label": str(body.get("label", "") or "").strip(),
                "from_room_id": from_room_id,
                "to_room_id": to_room_id,
            }
        ] + (
            [
                {
                    "way_id": _normalize_way_id(body.get("reverse_way_id") or f"to_{from_room_id}"),
                    "label": str(body.get("reverse_label", f"to {source_room.label()}") or "").strip(),
                    "from_room_id": to_room_id,
                    "to_room_id": from_room_id,
                }
            ]
            if bool(body.get("create_reverse", True))
            else []
        ):
            next_way_id = create_spec["way_id"]
            if next_way_id in world.ways or next_way_id in world.rooms:
                return _err(f"way_id already exists: {next_way_id}", 409)
            way_info = {"type": "way", "label": create_spec["label"], "to": create_spec["to_room_id"]}
            way_obj = Way(next_way_id, way_info)
            world.ways[next_way_id] = way_obj
            world.room_defs[next_way_id] = way_info
            _persist_definition(Path(world.root_path), next_way_id, way_info)
            source = world.rooms[create_spec["from_room_id"]]
            next_way_ids = _room_way_ids(source)
            if next_way_id not in next_way_ids:
                next_way_ids.append(next_way_id)
                _set_room_way_ids(source, next_way_ids)
                world.room_defs[source.room_id] = source.info
                _persist_definition(Path(world.root_path), source.room_id, source.info)
            created_way_ids.append(next_way_id)

        for room_id in {from_room_id, to_room_id}:
            _broadcast_room_updates(world.rooms[room_id], stage=True, exits=True)
        return jsonify(
            {
                "ok": True,
                "ways": [_serialize_way(world, created_way_id, world.ways[created_way_id]) for created_way_id in created_way_ids],
            }
        ), 201
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)


@blueprint.route("/api/world-editor/ways/<way_id>", methods=["PUT"])
def update_way(way_id):
    if g := _guard():
        return g
    try:
        _require_user()
        body = request.json or {}
        world = active_world()
        way_id = _normalize_way_id(way_id)
        way = world.ways.get(way_id)
        if way is None:
            return _err("way not found", 404)
        current_from_room_ids = [room_id for room_id, room in world.rooms.items() if way_id in _room_way_ids(room)]
        next_from_room_id = _normalize_room_id(body.get("from_room_id", current_from_room_ids[0] if current_from_room_ids else ""))
        to_room_id = _normalize_room_id(body.get("to_room_id", way.info.get("to", "")))
        if next_from_room_id not in world.rooms or to_room_id not in world.rooms:
            return _err("from_room_id and to_room_id must exist", 404)

        for room_id in current_from_room_ids:
            room = world.rooms[room_id]
            next_way_ids = [existing for existing in _room_way_ids(room) if existing != way_id]
            _set_room_way_ids(room, next_way_ids)
            world.room_defs[room.room_id] = room.info
            _persist_definition(Path(world.root_path), room.room_id, room.info)

        target_source_room = world.rooms[next_from_room_id]
        next_way_ids = _room_way_ids(target_source_room)
        if way_id not in next_way_ids:
            next_way_ids.append(way_id)
            _set_room_way_ids(target_source_room, next_way_ids)
            world.room_defs[target_source_room.room_id] = target_source_room.info
            _persist_definition(Path(world.root_path), target_source_room.room_id, target_source_room.info)

        way.info = {
            "type": "way",
            "label": str(body.get("label", way.label) or "").strip(),
            "to": to_room_id,
        }
        way.label = way.info["label"]
        world.room_defs[way_id] = way.info
        _persist_definition(Path(world.root_path), way_id, way.info)

        affected_rooms = set(current_from_room_ids + [next_from_room_id, to_room_id])
        for room_id in affected_rooms:
            room = world.rooms.get(room_id)
            if room is not None:
                room.ways = {existing_way_id: world.ways[existing_way_id] for existing_way_id in _room_way_ids(room) if existing_way_id in world.ways}
                _broadcast_room_updates(room, stage=True, exits=True)
        return jsonify({"ok": True, "way": _serialize_way(world, way_id, way)})
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)


@blueprint.route("/api/world-editor/ways/<way_id>", methods=["DELETE"])
def delete_way(way_id):
    if g := _guard():
        return g
    try:
        _require_user()
        world = active_world()
        way_id = _normalize_way_id(way_id)
        if way_id not in world.ways:
            return _err("way not found", 404)

        affected_room_ids = set()
        for room in world.rooms.values():
            next_way_ids = [existing_way_id for existing_way_id in _room_way_ids(room) if existing_way_id != way_id]
            if len(next_way_ids) != len(_room_way_ids(room)):
                _set_room_way_ids(room, next_way_ids)
                world.room_defs[room.room_id] = room.info
                _persist_definition(Path(world.root_path), room.room_id, room.info)
                affected_room_ids.add(room.room_id)
            for prop in room.props.values():
                if prop.metadata.get("exit_way_id") == way_id:
                    prop.metadata.pop("exit_way_id", None)
                    affected_room_ids.add(room.room_id)

        del world.ways[way_id]
        world.room_defs.pop(way_id, None)
        _delete_definition(Path(world.root_path), way_id)
        world.save_state(world.ws_id)

        for room_id in affected_room_ids:
            _broadcast_room_updates(world.rooms[room_id], stage=True, exits=True)
        return jsonify({"ok": True})
    except PermissionError as exc:
        return _err(str(exc), 401)
    except ValueError as exc:
        return _err(str(exc), 400)
