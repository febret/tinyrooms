import os
import random
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO

from . import char_data, char_editor, db, icons, object_editor, prop_editor_api, sprite_editor_api, sprites, user, world_editor_api
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


def _guard_world_server():
    """Return a 404 response when world-server feature is disabled, else None."""
    if not feature_enabled("world-server"):
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
