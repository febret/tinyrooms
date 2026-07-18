import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO

from . import char_data, char_editor, db, user
from .icons import DEFAULT_USER_ASSETS
from .world import active_world


STATIC_FOLDER = Path(__file__).parent.parent / "app"
CLIENT_FILENAME = "client.html"


# Create app and SocketIO
app = Flask(__name__, static_folder=str(STATIC_FOLDER), static_url_path="/app")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_char_editor_service = None


def _default_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "tinyrooms-char-editor"


def configure_char_editor(temp_root: Path | None = None):
    global _char_editor_service
    if _char_editor_service is not None:
        _char_editor_service.stop()
    config_path = Path(__file__).parent.parent / "data" / "ui" / "char-editor.yaml"
    make_sprite_script = Path(__file__).parent.parent / "tools" / "make-sprite"
    temp_dir = Path(temp_root) if temp_root else _default_temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    _char_editor_service = char_editor.CharacterEditorService(
        config_path=config_path,
        make_sprite_script=make_sprite_script,
        temp_root=temp_dir,
    )
    print(f"char-editor: service ready (temp_root={temp_dir})")


def shutdown_char_editor():
    global _char_editor_service
    if _char_editor_service is not None:
        _char_editor_service.stop()
        _char_editor_service = None


def char_editor_service() -> char_editor.CharacterEditorService:
    global _char_editor_service
    if _char_editor_service is None:
        configure_char_editor()
    return _char_editor_service # type: ignore


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


def _get_authenticated_username() -> str:
    """Get authenticated username from request, raising PermissionError if not authenticated."""
    return _require_rest_user()


def _handle_auth_error():
    """Create an authentication error response."""
    return _error_response("not authenticated", 401)


def _handle_value_error(err: ValueError, default_code: int = 400, code_for: dict | None = None):
    """Handle ValueError with optional custom status codes for specific error messages.
    
    Args:
        err: The ValueError to handle
        default_code: Default HTTP status code (default 400)
        code_for: Dict mapping error message substrings to HTTP codes
    
    Returns:
        Flask response tuple
    """
    if code_for is None:
        code_for = {}
    text = str(err)
    for substring, code in code_for.items():
        if substring in text:
            return _error_response(text, code)
    return _error_response(text, default_code)


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
    # Extract usernames from User instances
    usernames = [u.username for u in user.connected_users.values()]
    return jsonify({"connected": usernames})


@app.route("/api/char-editor/profile")
def char_editor_profile():
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    profile = char_editor_service().profile(username)
    return jsonify({"ok": True, **profile})


@app.route("/api/char-editor/requests", methods=["POST"])
def char_editor_submit_request():
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    payload = request.json or {}
    descriptors = payload.get("descriptors", {})
    try:
        req = char_editor_service().submit_request(username, descriptors)
    except ValueError as err:
        return _handle_value_error(err, code_for={"active request": 409})
    return jsonify({"ok": True, "request": req}), 201


@app.route("/api/char-editor/requests/<request_id>")
def char_editor_get_request(request_id):
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    try:
        req = char_editor_service().get_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/char-editor/requests/<request_id>", methods=["DELETE"])
def char_editor_cancel_request(request_id):
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    try:
        req = char_editor_service().cancel_request(username, request_id)
    except KeyError:
        return _error_response("request not found", 404)
    return jsonify({"ok": True, "request": req})


@app.route("/api/char-editor/queue")
def char_editor_queue():
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    summary = char_editor_service().queue_summary(username)
    return jsonify({"ok": True, "queue": summary})


@app.route("/api/char-editor/sprites/<sprite_id>", methods=["DELETE"])
def char_editor_discard_sprite(sprite_id):
    try:
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
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
        username = _get_authenticated_username()
    except PermissionError:
        return _handle_auth_error()
    try:
        payload = request.json or {}
        descriptors = payload.get("descriptors")
        char_state = char_editor_service().select_sprite(username, sprite_id, descriptors=descriptors)
    except FileNotFoundError:
        return _error_response("sprite not found", 404)
    except ValueError as err:
        return _error_response(str(err), 400)

    sprite_rel = char_state.get("current_sprite")
    _apply_selected_sprite_to_peep(username, sprite_rel) # type: ignore

    return jsonify({"ok": True, "char": char_state})
