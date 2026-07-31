import os
import random
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO

from . import user_data, char_editor, icons, object_editor, prop_editor_api, sprite_editor_api, sprites, user, world_editor_api
from .object import Object
from .world import active_world, save_generated_thing_def, serialize_prop_library


STATIC_FOLDER = Path(__file__).parent.parent / "app"
CLIENT_FILENAME = "client.html"


# Create app and SocketIO
app = Flask(__name__, static_folder=str(STATIC_FOLDER), static_url_path="/app")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
app.register_blueprint(sprite_editor_api.blueprint)
app.register_blueprint(prop_editor_api.blueprint)
app.register_blueprint(world_editor_api.blueprint)

_editor_registry: dict[str, Any] = {}
_enabled_features: set[str] = set()
_sprite_repository: sprites.SpriteRepository | None = None
_prop_repository = None  # prop_sets.PropRepository | None


def _configure_editor(name: str, service: Any) -> None:
    existing = _editor_registry.get(name)
    if existing is not None:
        existing.stop()
    _editor_registry[name] = service


def _shutdown_editor(name: str) -> None:
    service = _editor_registry.pop(name, None)
    if service is not None:
        service.stop()


def _get_editor(name: str, factory) -> Any:
    if name not in _editor_registry:
        factory()
    return _editor_registry[name]


def _default_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "tinyrooms-char-editor"


def _default_object_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "tinyrooms-object-editor"


def configure_char_editor(temp_root: Path | None = None):
    make_image_script = Path(__file__).parent.parent / "tools" / "make-image"
    temp_dir = Path(temp_root) if temp_root else _default_temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    _configure_editor(
        "char",
        char_editor.CharacterEditorService(make_image_script=make_image_script, temp_root=temp_dir),
    )
    print(f"char-editor: service ready (temp_root={temp_dir})")


def configure_object_editor(temp_root: Path | None = None):
    config_path = Path(__file__).parent.parent / "data" / "ui" / "object-editor.yaml"
    make_image_script = Path(__file__).parent.parent / "tools" / "make-image"
    temp_dir = Path(temp_root) if temp_root else _default_object_temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    _configure_editor(
        "object",
        object_editor.ObjectEditorService(
            config_path=config_path, make_image_script=make_image_script, temp_root=temp_dir
        ),
    )
    print(f"object-editor: service ready (temp_root={temp_dir})")


def shutdown_char_editor():
    _shutdown_editor("char")


def shutdown_object_editor():
    _shutdown_editor("object")


def char_editor_service() -> char_editor.CharacterEditorService:
    return _get_editor("char", configure_char_editor)  # type: ignore


def object_editor_service() -> object_editor.ObjectEditorService:
    return _get_editor("object", configure_object_editor)  # type: ignore


def _object_assets_root(world_id: str) -> Path:
    if not world_id or "/" in world_id or "\\" in world_id or ".." in world_id:
        raise ValueError("invalid world id")
    return Path(__file__).parent.parent / "data" / "object_assets" / world_id


def _server_images_root() -> Path:
    return Path(__file__).parent.parent / "data" / "images"


def configure_features(features: set[str] | list[str] | tuple[str, ...]):
    global _enabled_features
    normalized = {str(feature).strip() for feature in features if str(feature).strip()}
    print(f"enabled features: {', '.join(sorted(normalized))}")
    _enabled_features = normalized


def feature_enabled(feature_name: str) -> bool:
    print(f"checking if feature '{feature_name}' is enabled: {'yes' if feature_name in _enabled_features else 'no'}")
    return feature_name in _enabled_features


def _require_feature(feature_name: str):
    if not feature_enabled(feature_name):
        raise PermissionError(f"feature '{feature_name}' is disabled")


def _sprite_repo(force_reindex: bool = False) -> sprites.SpriteRepository:
    global _sprite_repository
    world_root = Path(active_world().root_path)
    if (
        _sprite_repository is None
        or _sprite_repository.world_root_path != world_root
    ):
        _sprite_repository = sprites.SpriteRepository(world_root)
        _sprite_repository.reindex()
        return _sprite_repository
    if force_reindex:
        _sprite_repository.reindex()
    return _sprite_repository


def _prop_repo(force_reindex: bool = False):
    global _prop_repository
    from . import prop_sets as prop_sets_module
    world_root = Path(active_world().root_path)
    if _prop_repository is None or _prop_repository.world_root_path != world_root:
        _prop_repository = prop_sets_module.PropRepository(world_root)
        _prop_repository.reindex()
        return _prop_repository
    if force_reindex:
        _prop_repository.reindex()
    return _prop_repository


def _require_rest_user() -> str:
    token = request.headers.get("X-TR-Auth", "").strip()
    if token:
        for online_user in user.connected_users.values():
            if getattr(online_user, "rest_token", "") == token:
                return online_user.username
    username = session.get("username")
    if not username:
        raise PermissionError("not authenticated")
    if user.find_online(username) is None:
        raise PermissionError("session user is not connected")
    return username


def _error_response(message: str, code: int):
    return jsonify({"ok": False, "error": message}), code


def _guard_world_server():
    """Return a 404 response when world-server feature is disabled, else None."""
    if not feature_enabled("world-server"):
        print("world-server feature is disabled; returning 404 for request")
        return jsonify({"ok": False, "error": "world-server feature disabled"}), 404
    return None

def _update_peep_display_and_broadcast(username: str, display_assets: dict) -> None:
    """Update an online user's peep display assets and broadcast the room update.
    
    Args:
        username: The username whose peep should be updated
        display_assets: Dictionary of display assets to apply
    """
    online = user.find_online(username)
    if online is not None and online.peep is not None:
        online.peep._display_assets = display_assets
        if online.room is not None:
            online.room.broadcast_room_object_update(
                online.peep, change_type="upsert", entity_type="peep", owner_username=username
            )


def _apply_character_state_to_peep(username: str, char_state: dict[str, Any]) -> None:
    online = user.find_online(username)
    if online is None or online.peep is None:
        return
    online.peep.info["description"] = str(char_state.get("description") or "")
    display_assets = char_editor.build_character_display_assets(
        username,
        char_state,
        active_world().root_path,
        sprite_repo=_sprite_repo(force_reindex=False),
    )
    _update_peep_display_and_broadcast(username, display_assets)


def _random_suffix(length: int = 6) -> str:
    return "".join(random.choices("0123456789abcdef", k=length))


def _create_object_in_user_room(username: str, info: dict) -> tuple[Object, dict]:
    online = user.find_online(username)
    if online is None or online.room is None:
        raise ValueError("user is not in a room")
    room = online.room
    room_id = room.id()
    thing_id = f"generated_thing_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_random_suffix(4)}"
    obj_id = f"{thing_id}-{_random_suffix(5)}"
    normalized_info = dict(info)
    save_generated_thing_def(thing_id, normalized_info)
    obj = Object(obj_id, thing_id, normalized_info, room_id, owner_id=username)
    obj.x = int(getattr(online.peep, "x", 32))
    obj.y = int(getattr(online.peep, "y", 32))
    obj.orientation = "front"
    obj.layer = 0
    obj.z_order = room.next_z()
    obj._display_assets = icons.build_display_assets(info, active_world().root_path)  # type: ignore

    world = active_world()
    world.thing_defs[thing_id] = normalized_info
    world.objs[obj_id] = obj
    room.objs[obj_id] = obj
    room.broadcast_room_object_update(obj, change_type="upsert", entity_type="object")
    world.save_state(world.ws_id)
    return obj, room._serialize_foreground_entity(obj, entity_type="object")


def _persist_object_asset(source_path: Path, world_id: str, prefix: str = "obj") -> str:
    root = _object_assets_root(world_id)
    root.mkdir(parents=True, exist_ok=True)
    asset_name = f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_random_suffix(8)}.png"
    final_path = root / asset_name
    try:
        shutil.copy2(source_path, final_path)
    except OSError as err:
        raise ValueError(f"failed to persist object asset: {err}") from err
    return f"/object-assets/{world_id}/{asset_name}"


@app.route("/")
def client():
    if g := _guard_world_server():
        return g
    return send_from_directory(str(STATIC_FOLDER), CLIENT_FILENAME)


@app.route("/world/<path:filename>")
def world_data(filename):
    """Serve static files from the world's root path"""
    if g := _guard_world_server():
        return g
    if active_world().root_path is None:
        return jsonify({"error": "World not loaded"}), 404
    return send_from_directory(str(active_world().root_path), filename)


@app.route("/user-assets/<username>/<path:filename>")
def user_asset_data(username, filename):
    if g := _guard_world_server():
        return g
    try:
        root = user_data.user_root(username)
    except ValueError:
        return jsonify({"error": "invalid username"}), 400
    asset_path = root / filename
    if not asset_path.exists():
        return jsonify({"error": "asset not found"}), 404
    return send_from_directory(str(root), filename)


@app.route("/object-assets/<world_id>/<path:filename>")
def object_asset_data(world_id, filename):
    try:
        root = _object_assets_root(world_id)
    except ValueError:
        return jsonify({"error": "invalid world id"}), 400
    asset_path = root / filename
    if not asset_path.exists():
        return jsonify({"error": "asset not found"}), 404
    return send_from_directory(str(root), filename)


@app.route("/server-images/<path:filename>")
def server_image_data(filename):
    if g := _guard_world_server():
        return g
    root = _server_images_root()
    asset_path = root / filename
    if not asset_path.exists():
        return jsonify({"error": "asset not found"}), 404
    return send_from_directory(str(root), filename)


@app.route("/sprites/<scope>/<path:filename>")
def sprite_asset_data(scope, filename):
    if scope not in {"server", "world"}:
        return jsonify({"error": "invalid sprite scope"}), 404
    repo = _sprite_repo(force_reindex=False)
    stem = Path(filename).stem
    record = repo.get(scope, stem)
    if record is None or not record.has_image or record.image_path is None:
        return jsonify({"error": "sprite image not found"}), 404
    return send_from_directory(str(record.image_path.parent), record.image_path.name)


@app.route("/props/<scope>/<path:filename>")
def prop_asset_data(scope, filename):
    if scope not in {"server", "world"}:
        return jsonify({"error": "invalid prop scope"}), 404
    repo = _prop_repo(force_reindex=False)
    stem = Path(filename).stem
    record = repo.get(scope, stem)
    if record is None or not record.has_image or record.image_path is None:
        return jsonify({"error": "prop image not found"}), 404
    return send_from_directory(str(record.image_path.parent), record.image_path.name)


@app.route("/register", methods=["POST"])
def register():
    if g := _guard_world_server():
        return g
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"ok": False, "error": "username and password required"}), 400
    created = user_data.create_user_profile(username, password)
    if not created:
        return jsonify({"ok": False, "error": "username already exists"}), 409
    return jsonify({"ok": True, "message": "user created"}), 201


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("username", None)
    return jsonify({"ok": True})


@app.route("/connected")
def list_connected():
    usernames = [u.username for u in user.connected_users.values()]
    return jsonify({"connected": usernames})


@app.route("/api/props/library")
def props_library():
    if g := _guard_world_server():
        return g
    try:
        _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    world = active_world()
    return jsonify({"ok": True, "world_id": world.ws_id, "props": serialize_prop_library(world)})


@app.route("/api/char-editor/profile")
def char_editor_profile():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    profile = char_editor_service().profile(username, _sprite_repo(force_reindex=False))
    return jsonify({"ok": True, **profile})


@app.route("/api/char-editor/profile", methods=["PUT"])
def char_editor_update_profile():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    try:
        current_sprite = payload["current_sprite"] if "current_sprite" in payload else char_editor.UNSET
        updated = char_editor_service().update_profile(
            username,
            _sprite_repo(force_reindex=False),
            description=payload.get("description"),
            current_sprite=current_sprite,
        )
    except ValueError as err:
        return _error_response(str(err), 400)
    _apply_character_state_to_peep(username, updated)
    return jsonify({"ok": True, "char": updated})


@app.route("/api/char-editor/main-image", methods=["POST"])
def char_editor_generate_main_image():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    try:
        current_sprite = payload["current_sprite"] if "current_sprite" in payload else char_editor.UNSET
        char_state = char_editor_service().generate_main_image(
            username,
            _sprite_repo(force_reindex=False),
            description=payload.get("description"),
            current_sprite=current_sprite,
        )
    except FileNotFoundError:
        return _error_response("sprite not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    _apply_character_state_to_peep(username, char_state)
    return jsonify({"ok": True, "char": char_state})


@app.route("/api/object-editor/profile")
def object_editor_profile():
    try:
        _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    profile = object_editor_service().profile(_sprite_repo(force_reindex=False))
    return jsonify({"ok": True, **profile})


@app.route("/api/object-editor/image", methods=["POST"])
def object_editor_generate_image():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    description = payload.get("description", "")
    try:
        generated = object_editor_service().generate_image(
            username,
            description,
            previous_image=payload.get("previous_image"),
        )
    except ValueError as err:
        return _error_response(str(err), 400)
    return jsonify({"ok": True, "image": generated}), 200


@app.route("/api/object-editor/create", methods=["POST"])
def object_editor_create_thing():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    description = payload.get("description", "")
    try:
        world_id = active_world().ws_id
        sprite_ref = object_editor_service().validate_current_sprite(
            payload.get("current_sprite"),
            _sprite_repo(force_reindex=False),
        )
        image_path = object_editor_service().validate_image_path(username, payload.get("image_path"))
        persistent_image_url = None
        if image_path:
            source_path = object_editor.image_file_path(username, image_path)
            persistent_image_url = _persist_object_asset(source_path, world_id, prefix="obj_img")
        info = object_editor_service().build_object_info(
            username=username,
            description=description,
            current_sprite=sprite_ref,
            image_asset_url=persistent_image_url,
        )
        created_obj, serialized = _create_object_in_user_room(username, info)
    except FileNotFoundError:
        return _error_response("image not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    return jsonify({"ok": True, "object_id": created_obj.obj_id, "entity": serialized}), 201


# ---------------------------------------------------------------------------
# Gameplay REST API
# ---------------------------------------------------------------------------

@app.route("/api/gameplay/status")
def gameplay_status():
    """Return the authenticated user's current gameplay state."""
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    from . import gameplay as _gp, user_data as _ud, user as _user
    kudos = _ud.read_kudos(username)
    level_info = _gp.compute_level(kudos.get("total_received", 0))
    online = _user.find_online(username)
    if online is not None:
        juice = online.juice
        max_juice = online.max_juice
        bops = online.bops
        traits = list(online.traits)
    else:
        profile = _ud.read_profile(username) or {}
        juice = float(profile.get("juice") or _gp.BASE_MAX_JUICE)
        bops = int(profile.get("bops") or 0)
        traits = list(profile.get("traits") or [])
        max_juice = _gp.max_juice(level_info["level"])
    return jsonify({
        "ok": True,
        "username": username,
        "level": level_info["level"],
        "level_title": level_info["title"],
        "level_icon": level_info["icon"],
        "kudos_received": kudos.get("total_received", 0),
        "kudos_next_level": level_info["next_threshold"],
        "kudos_required": level_info["kudos_required"],
        "daily_given_remaining": kudos.get("daily_given_remaining", 0),
        "juice": round(juice, 2),
        "max_juice": round(max_juice, 2),
        "bops": bops,
        "traits": traits,
    })


@app.route("/api/gameplay/give-kudos", methods=["POST"])
def gameplay_give_kudos():
    """Give kudos to another user.  Body: {username, amount}."""
    try:
        giver_name = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    from . import gameplay as _gp, user_data as _ud, user as _user
    payload = request.json or {}
    target_name = str(payload.get("username") or "").strip()
    try:
        amount = max(1, int(payload.get("amount", 1)))
    except (TypeError, ValueError):
        amount = 1
    if not target_name:
        return _error_response("username is required", 400)
    if target_name == giver_name:
        return _error_response("cannot give kudos to yourself", 400)
    if _ud.read_profile(target_name) is None:
        return _error_response(f"user '{target_name}' not found", 404)

    giver_kudos = _ud.read_kudos(giver_name)
    remaining = giver_kudos.get("daily_given_remaining", 0)
    if remaining <= 0:
        return _error_response("no kudos left to give today", 409)
    actual = min(amount, remaining)

    given_map = dict(giver_kudos.get("given", {}))
    given_map[target_name] = given_map.get(target_name, 0) + actual
    _ud.write_kudos(
        giver_name,
        total_given_all_time=giver_kudos.get("total_given_all_time", 0) + actual,
        daily_given_remaining=remaining - actual,
        given=given_map,
    )
    recv_kudos = _ud.read_kudos(target_name)
    recv_map = dict(recv_kudos.get("received", {}))
    recv_map[giver_name] = recv_map.get(giver_name, 0) + actual
    _ud.write_kudos(
        target_name,
        total_received=recv_kudos.get("total_received", 0) + actual,
        received=recv_map,
    )

    # Notify both users if online
    giver_online = _user.find_online(giver_name)
    if giver_online:
        giver_online.update_status()
    target_online = _user.find_online(target_name)
    if target_online:
        target_online.status_stale = True
        target_online.update_status()

    return jsonify({"ok": True, "given": actual, "daily_given_remaining": remaining - actual})


@app.route("/api/gameplay/buy-juice", methods=["POST"])
def gameplay_buy_juice():
    """Purchase a juice pack with Bops.  Body: {pack: 'small'|'medium'|'large'}."""
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    from . import gameplay as _gp, user_data as _ud, user as _user
    payload = request.json or {}
    pack_name = str(payload.get("pack") or "").strip().lower()
    pack = _gp.JUICE_PACKS.get(pack_name)
    if pack is None:
        return _error_response(f"unknown pack '{pack_name}'. valid: {', '.join(_gp.JUICE_PACKS)}", 400)

    online = _user.find_online(username)
    if online is None:
        return _error_response("user is not online", 403)
    if online.bops < pack["bops_cost"]:
        return _error_response(f"not enough bops (need {pack['bops_cost']}, have {online.bops})", 409)
    online.bops -= pack["bops_cost"]
    online.juice = online._juice + pack["juice_amount"]
    _ud.save_user_state(online)
    online.update_status()
    return jsonify({
        "ok": True,
        "pack": pack_name,
        "juice": round(online.juice, 2),
        "max_juice": round(online.max_juice, 2),
        "bops": online.bops,
    })


