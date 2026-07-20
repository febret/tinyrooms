import os
import random
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO

from . import char_data, char_editor, db, icons, object_editor, prop_editor_api, sprite_editor_api, sprites, user
from .icons import DEFAULT_USER_ASSETS
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

_char_editor_service = None
_object_editor_service = None
_enabled_features: set[str] = set()
_sprite_repository: sprites.SpriteRepository | None = None
_prop_repository = None  # prop_sets.PropRepository | None


def _default_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "tinyrooms-char-editor"


def _default_object_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "tinyrooms-object-editor"


def _object_assets_root(world_id: str) -> Path:
    if not world_id or "/" in world_id or "\\" in world_id or ".." in world_id:
        raise ValueError("invalid world id")
    return Path(__file__).parent.parent / "data" / "object_assets" / world_id


def configure_char_editor(temp_root: Path | None = None):
    global _char_editor_service
    if _char_editor_service is not None:
        _char_editor_service.stop()
    config_path = Path(__file__).parent.parent / "data" / "ui" / "char-editor.yaml"
    make_image_script = Path(__file__).parent.parent / "tools" / "make-image"
    temp_dir = Path(temp_root) if temp_root else _default_temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    _char_editor_service = char_editor.CharacterEditorService(
        config_path=config_path,
        make_image_script=make_image_script,
        temp_root=temp_dir,
    )
    print(f"char-editor: service ready (temp_root={temp_dir})")


def configure_object_editor(temp_root: Path | None = None):
    global _object_editor_service
    if _object_editor_service is not None:
        _object_editor_service.stop()
    config_path = Path(__file__).parent.parent / "data" / "ui" / "object-editor.yaml"
    make_image_script = Path(__file__).parent.parent / "tools" / "make-image"
    temp_dir = Path(temp_root) if temp_root else _default_object_temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    _object_editor_service = object_editor.ObjectEditorService(
        config_path=config_path,
        make_image_script=make_image_script,
        temp_root=temp_dir,
    )
    print(f"object-editor: service ready (temp_root={temp_dir})")


def shutdown_char_editor():
    global _char_editor_service
    if _char_editor_service is not None:
        _char_editor_service.stop()
        _char_editor_service = None


def shutdown_object_editor():
    global _object_editor_service
    if _object_editor_service is not None:
        _object_editor_service.stop()
        _object_editor_service = None


def char_editor_service() -> char_editor.CharacterEditorService:
    global _char_editor_service
    if _char_editor_service is None:
        configure_char_editor()
    return _char_editor_service # type: ignore


def object_editor_service() -> object_editor.ObjectEditorService:
    global _object_editor_service
    if _object_editor_service is None:
        configure_object_editor()
    return _object_editor_service  # type: ignore


def configure_features(features: set[str] | list[str] | tuple[str, ...]):
    global _enabled_features
    normalized = {str(feature).strip() for feature in features if str(feature).strip()}
    _enabled_features = normalized


def feature_enabled(feature_name: str) -> bool:
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


def _apply_selected_sprite_to_peep(username: str, sprite_rel: str) -> None:
    """Apply a selected sprite to an online user's peep and broadcast the update.
    
    Args:
        username: The username whose peep should be updated
        sprite_rel: The relative path to the sprite file
    """
    if isinstance(sprite_rel, str) and sprite_rel:
        sprite_url = char_data.sprite_url(username, sprite_rel)
        display_assets = {
            "icon": sprite_url,
            "img": sprite_url,
            "sprite": sprite_url,
        }
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


def _persist_generated_object_icon(icon_source_path: Path, world_id: str) -> str:
    root = _object_assets_root(world_id)
    root.mkdir(parents=True, exist_ok=True)
    icon_name = f"obj_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_random_suffix(8)}.png"
    final_path = root / icon_name
    try:
        shutil.copy2(icon_source_path, final_path)
    except OSError as err:
        raise ValueError(f"failed to persist object icon: {err}") from err
    return f"/object-assets/{world_id}/{icon_name}"


@app.route("/")
def client():
    return send_from_directory(str(STATIC_FOLDER), CLIENT_FILENAME)


@app.route("/world/<path:filename>")
def world_data(filename):
    """Serve static files from the world's root path"""
    if active_world().root_path is None:
        return jsonify({"error": "World not loaded"}), 404
    return send_from_directory(str(active_world().root_path), filename)


@app.route("/user-assets/<username>/<path:filename>")
def user_asset_data(username, filename):
    try:
        root = char_data.user_root(username)
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
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"ok": False, "error": "username and password required"}), 400
    created = db.create_user(username, password)
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
    profile = char_editor_service().profile(username)
    return jsonify({"ok": True, **profile})


@app.route("/api/char-editor/requests", methods=["POST"])
def char_editor_submit_request():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    descriptors = payload.get("descriptors", {})
    try:
        req = char_editor_service().submit_request(username, descriptors)
    except ValueError as err:
        code = 409 if "active request" in str(err) else 400
        return _error_response(str(err), code)
    return jsonify({"ok": True, "request": req}), 201


@app.route("/api/char-editor/requests/<request_id>")
def char_editor_get_request(request_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        req = char_editor_service().get_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/char-editor/requests/<request_id>", methods=["DELETE"])
def char_editor_cancel_request(request_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        req = char_editor_service().cancel_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/char-editor/queue")
def char_editor_queue():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    summary = char_editor_service().queue_summary(username)
    return jsonify({"ok": True, "queue": summary})


@app.route("/api/char-editor/sprites/<sprite_id>", methods=["DELETE"])
def char_editor_discard_sprite(sprite_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        cleared_current = char_editor_service().discard_sprite(username, sprite_id)
    except FileNotFoundError:
        return _error_response("sprite not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    if cleared_current:
        _update_peep_display_and_broadcast(username, dict(DEFAULT_USER_ASSETS))
    return jsonify({"ok": True})


@app.route("/api/char-editor/sprites/<sprite_id>/select", methods=["POST"])
def char_editor_select_sprite(sprite_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        payload = request.json or {}
        descriptors = payload.get("descriptors")
        char_state = char_editor_service().select_sprite(username, sprite_id, descriptors=descriptors)
    except FileNotFoundError:
        return _error_response("sprite not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    _apply_selected_sprite_to_peep(username, char_state.get("current_sprite"))  # type: ignore
    return jsonify({"ok": True, "char": char_state})


@app.route("/api/object-editor/profile")
def object_editor_profile():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    profile = object_editor_service().profile(username)
    return jsonify({"ok": True, **profile})


@app.route("/api/object-editor/requests", methods=["POST"])
def object_editor_submit_request():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    description = payload.get("description", "")
    try:
        req = object_editor_service().submit_request(username, description)
    except ValueError as err:
        code = 409 if "active request" in str(err) else 400
        return _error_response(str(err), code)
    return jsonify({"ok": True, "request": req}), 201


@app.route("/api/object-editor/requests/<request_id>")
def object_editor_get_request(request_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        req = object_editor_service().get_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/object-editor/requests/<request_id>", methods=["DELETE"])
def object_editor_cancel_request(request_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        req = object_editor_service().cancel_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/object-editor/queue")
def object_editor_queue():
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    summary = object_editor_service().queue_summary(username)
    return jsonify({"ok": True, "queue": summary})


@app.route("/api/object-editor/icons/<icon_id>", methods=["DELETE"])
def object_editor_discard_icon(icon_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    try:
        object_editor_service().discard_icon(username, icon_id)
    except FileNotFoundError:
        return _error_response("icon not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    return jsonify({"ok": True})


@app.route("/api/object-editor/icons/<icon_id>/create", methods=["POST"])
def object_editor_create_thing(icon_id):
    try:
        username = _require_rest_user()
    except PermissionError:
        return _error_response("not authenticated", 401)
    payload = request.json or {}
    description = payload.get("description", "")
    try:
        world_id = active_world().ws_id
        icon_path = object_editor.icon_file_path(username, icon_id)
        persistent_icon_url = _persist_generated_object_icon(icon_path, world_id)
        info = object_editor_service().build_object_info(
            username=username,
            icon_id=icon_id,
            description=description,
            icon_asset_url=persistent_icon_url,
        )
        created_obj, serialized = _create_object_in_user_room(username, info)
    except FileNotFoundError:
        return _error_response("icon not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)
    return jsonify({"ok": True, "object_id": created_obj.obj_id, "entity": serialized}), 201

