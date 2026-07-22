from flask import request, session
from flask_socketio import emit
import functools
import secrets
from uuid import uuid4

from . import message, user, server, user_data, icons, emotes, decorators as decorator_module
from .prop import Prop
from .world import active_world
from . import peep_behavior as _peep_behavior

def _save_world():
    """Persist the active world state."""
    world = active_world()
    world.save_state(world.ws_id)


def _require_room_user():
    """Return (user_obj, room) for the current socket request, or emit an error and return (None, None)."""
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return None, None
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"})
        return None, None
    return user_obj, room


def _normalize_inventory_actions(raw_actions):
    if raw_actions is None:
        return []

    def _normalize_entry(entry, idx: int):
        if isinstance(entry, str):
            commands = entry.strip()
            if not commands:
                return None
            return {"label": "Use Item" if idx == 1 else f"Action {idx}", "commands": commands}
        if isinstance(entry, dict):
            commands = str(entry.get("commands") or entry.get("command") or "").strip()
            if not commands:
                return None
            label = str(entry.get("label") or f"Action {idx}").strip() or f"Action {idx}"
            return {"label": label, "commands": commands}
        return None

    if isinstance(raw_actions, (str, dict)):
        normalized = _normalize_entry(raw_actions, 1)
        return [normalized] if normalized else []

    if isinstance(raw_actions, list):
        out = []
        for idx, entry in enumerate(raw_actions, start=1):
            normalized = _normalize_entry(entry, idx)
            if normalized:
                out.append(normalized)
        return out

    return []


def _inventory_actions_for_object(obj):
    obj_info = getattr(obj, "info", {}) or {}
    return _normalize_inventory_actions(obj_info.get("inventory_action"))


def _find_room_entity(room, entity_type: str, entity_id: str):
    if entity_type == "object":
        return room.objs.get(entity_id)
    if entity_type == "peep":
        return room.peeps.get(entity_id)
    if entity_type == "prop":
        return room.props.get(entity_id)
    return None


def _broadcast_decorator_update(room, entity, entity_type: str):
    if entity_type == "object":
        room.broadcast_room_object_update(entity, change_type='upsert', entity_type='object')
        return
    if entity_type == "peep":
        room.broadcast_room_object_update(
            entity,
            change_type='upsert',
            entity_type='peep',
            owner_username=getattr(entity, "peep_id", ""),
        )
        return
    if entity_type == "prop":
        for room_user in room.users.values():
            room.send_room_stage_view(room_user)
        return


# Socket.IO events
@server.socketio.on("connect")
def handle_connect():
    print(f"connect: sid={getattr(request, 'sid', None)}")
    emit("connected", {"message": "connected to server"})
    if not server.feature_enabled("world-server"):
        return
    if len(emotes.emote_defs) == 0:
        emotes.load_emotes()
    client_emotes = {k: v for k, v in emotes.emote_defs.items() if '.' not in k}
    emit("emotes_def", {"emotes": client_emotes}, to=getattr(request, 'sid', None))


@server.socketio.on("disconnect")
def handle_disconnect():
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.pop(sid, None)
    print(f"disconnect: sid={sid} username={user_obj.username if user_obj else None}")
    if user_obj:
        # Save user's state before removing from room
        user_data.save_user_state(user_obj)
        if user_obj.room:
            user_obj.room.remove_user(user_obj)
        if getattr(user_obj, 'world', None):
            user_obj.world.peeps.pop(user_obj.username, None)


@server.socketio.on("login")
def handle_login(data):
    """
    Expect data: {"username": "...", "password": "..."}
    Sends back either:
      - "login_success" with {"username":...}
      - "login_failed" with {"error": "..."}
    """
    if not server.feature_enabled("world-server"):
        emit("login_failed", {"error": "world-server feature disabled"})
        return
    sid = getattr(request, 'sid', None)
    username = (data or {}).get("username")
    password = (data or {}).get("password")
    if not username or not password:
        emit("login_failed", {"error": "username and password required"})
        return

    profile = user_data.read_profile(username)
    if profile is None:
        emit("login_failed", {"error": "invalid credentials"})
        return

    if not user_data.check_user_password(username, password):
        emit("login_failed", {"error": "invalid credentials"})
        return

    # Check if user is already logged in
    if any(u.username == username for u in user.connected_users.values()):
        emit("login_failed", {"error": "user already logged in"})
        print(f"login rejected: {username} is already logged in")
        return

    # Create User instance and store it
    user_obj = user.User(username, sid, active_world(), persisted_state=profile)
    user_obj.rest_token = secrets.token_urlsafe(24)
    # Load saved skin from profile
    user_obj.skin = profile.get("skin") or 'base'
    user_obj.skin_stale = True
    user.connected_users[sid] = user_obj
    session["username"] = username
    user_data.save_user_state(user_obj)

    emit("login_success", {"username": username, "rest_token": user_obj.rest_token})
    _emit_inventory_update(user_obj)

    print(f"login success: {username} (sid={sid}) - added to room {user_obj.room.room_id if user_obj.room else None}")


@server.socketio.on("message")
def handle_message(data):
    """
    Expect data: {"text": "..."}
    Only accepts messages if client is authenticated.
    Dispatches emotes from the parsed message.
    """
    sid = request.sid # type: ignore
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return
    text = (data or {}).get("text", "").strip()
    if not text:
        return

    # Route admin commands (/) and superuser commands (:)
    from . import commands
    if text.startswith("/"):
        commands.dispatch_admin(user_obj, text)
        return
    if text.startswith(":"):
        commands.dispatch(user_obj, text, active_world())
        return

    parsed = message.parse_message(text, user_obj, user_obj.room)

    # Handle emotes in order of appearance
    for emote_inv in parsed.emotes:
        emotes.do_emote(
            emote_inv.emote_id,
            emote_inv.refs,
            user_obj,
            user_obj.room,
            extra_text=emote_inv.extra_text,
        )

    # Dispatch on_message to any NPC peeps referenced in the message
    from .peep import Peep
    for ref in parsed.refs:
        if isinstance(ref, Peep) and getattr(ref, 'type', 'user') == 'npc':
            _peep_behavior.call_handler(ref, 'on_message', user_obj, text)


# Optional: simple ping from client
@server.socketio.on("heartbeat")
def handle_heartbeat(data):
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if user_obj is None:
        return
    if user_obj.actions_stale:
        client_emotes = {k: v for k, v in emotes.emote_defs.items() if '.' not in k}
        emit("emotes_def", {"emotes": client_emotes}, to=sid)
        user_obj.actions_stale = False
    if user_obj.client_stale:
        print("Reloading client for user:", user_obj.username)
        emit("reload_client", {}, to=sid)
        user_obj.client_stale = False
    if user_obj.styles_stale:
        emit("reload_styles", {}, to=sid)
        user_obj.styles_stale = False
    if user_obj.skin_stale:
        emit("set_skin", {"skin": user_obj.skin}, to=sid)
        user_obj.skin_stale = False


@server.socketio.on("room_move_entity")
def handle_room_move_entity(data):
    user_obj, room = _require_room_user()
    if user_obj is None:
        return

    entity_type = (data or {}).get("entity_type", "")
    entity_id = (data or {}).get("entity_id", "")
    x = int((data or {}).get("x", 0))
    y = int((data or {}).get("y", 0))
    orientation = (data or {}).get("orientation", "front")

    if entity_type == "peep":
        target_user = room.users.get(entity_id)
        if target_user is None:
            emit("error", {"error": "peep not found"})
            return
        if not room.can_user_move_peep(user_obj, entity_id):
            emit("error", {"error": "you cannot move this peep"})
            return
        target_user.peep.x = x
        target_user.peep.y = y
        target_user.peep.orientation = orientation
        target_user.peep.z_order = room.next_z()
        room.broadcast_room_object_update(target_user.peep, change_type='upsert', entity_type='peep', owner_username=entity_id)
        return

    if entity_type == "object":
        target_obj = room.objs.get(entity_id)
        if target_obj is None:
            emit("error", {"error": "object not found"})
            return
        target_obj.x = x
        target_obj.y = y
        target_obj.orientation = orientation
        target_obj.z_order = room.next_z()
        room.broadcast_room_object_update(target_obj, change_type='upsert', entity_type='object')
        return

    emit("error", {"error": "invalid entity type"})


@server.socketio.on("room_edit_prop")
def handle_room_edit_prop(data):
    user_obj, room = _require_room_user()
    if user_obj is None:
        return
    if not room.can_user_edit_props(user_obj):
        emit("error", {"error": "only room owner can edit props"})
        return

    prop_instance_id = (data or {}).get("prop_instance_id", "")
    prop = room.props.get(prop_instance_id)
    if prop is None:
        emit("error", {"error": "prop not found"})
        return
    prop.x = int((data or {}).get("x", prop.x))
    prop.y = int((data or {}).get("y", prop.y))
    prop.orientation = (data or {}).get("orientation", prop.orientation)
    prop.z_order = room.next_z()

    for room_user in room.users.values():
        room.send_room_stage_view(room_user)


@server.socketio.on("room_save_props")
def handle_room_save_props(data):
    user_obj, room = _require_room_user()
    if user_obj is None:
        return
    if not room.can_user_edit_props(user_obj):
        emit("error", {"error": "only room owner can edit props"})
        return

    raw_props = (data or {}).get("props")
    if not isinstance(raw_props, list):
        emit("error", {"error": "props must be a list"})
        return

    world = active_world()
    next_props: dict[str, Prop] = {}
    seen_ids: set[str] = set()
    orientation_values = {"front", "back", "left", "right"}
    z_counter = max(10, room._z_counter)
    for raw_prop in raw_props:
        if not isinstance(raw_prop, dict):
            emit("error", {"error": "invalid prop entry"})
            return
        prop_id = str(raw_prop.get("prop_id", "")).strip()
        if not prop_id:
            emit("error", {"error": "prop_id is required"})
            return
        if prop_id not in world.prop_defs:
            emit("error", {"error": f"unknown prop_id '{prop_id}'"})
            return
        prop_instance_id = str(raw_prop.get("prop_instance_id", "")).strip()
        if not prop_instance_id:
            prop_instance_id = f"{room.room_id}-{prop_id}-{uuid4().hex[:8]}"
        if prop_instance_id in seen_ids:
            emit("error", {"error": "duplicate prop_instance_id in payload"})
            return
        seen_ids.add(prop_instance_id)

        try:
            x = int(raw_prop.get("x", 0))
            y = int(raw_prop.get("y", 0))
        except (TypeError, ValueError):
            emit("error", {"error": "x and y must be integers"})
            return
        orientation = str(raw_prop.get("orientation", "front"))
        if orientation not in orientation_values:
            emit("error", {"error": f"invalid orientation '{orientation}'"})
            return

        merged_info = dict(world.prop_defs.get(prop_id, {}))
        merged_info.update({
            "x": x,
            "y": y,
            "orientation": orientation,
            "layer": 0,
            "z_order": z_counter + 1,
        })
        z_counter += 1
        prop = Prop(prop_instance_id, prop_id, merged_info, room.room_id)
        prop._display_assets = icons._build_prop_display_assets(prop_id, server._prop_repo())
        exit_way_id = str(raw_prop.get("exit_way_id") or "").strip() or None
        if exit_way_id:
            if exit_way_id not in room.ways:
                emit("error", {"error": f"unknown exit way '{exit_way_id}'"})
                return
            prop.metadata["exit_way_id"] = exit_way_id
        next_props[prop_instance_id] = prop

    room.props = next_props
    room._z_counter = z_counter
    world.save_state(world.ws_id)

    for room_user in room.users.values():
        room.send_room_stage_view(room_user)


@server.socketio.on("apply_decorator")
def handle_apply_decorator(data):
    user_obj, room = _require_room_user()
    if user_obj is None:
        return
    entity_type = str((data or {}).get("entity_type", "")).strip()
    entity_id = str((data or {}).get("entity_id", "")).strip()
    deco_id = str((data or {}).get("deco_id", "")).strip()
    if not entity_type or not entity_id or not deco_id:
        emit("error", {"error": "entity_type, entity_id, and deco_id are required"})
        return
    try:
        canonical_deco_id = decorator_module.normalize_decorator_reference(deco_id)
    except ValueError:
        emit("error", {"error": "invalid decorator reference"})
        return
    world = active_world()
    if canonical_deco_id not in world.deco_defs:
        emit("error", {"error": f"unknown decorator '{canonical_deco_id}'"})
        return
    entity = _find_room_entity(room, entity_type, entity_id)
    if entity is None:
        emit("error", {"error": f"{entity_type} not found"})
        return
    if not hasattr(entity, "decorators") or not isinstance(entity.decorators, list):
        entity.decorators = []
    if canonical_deco_id not in entity.decorators:
        entity.decorators.append(canonical_deco_id)
    _broadcast_decorator_update(room, entity, entity_type)


@server.socketio.on("remove_decorator")
def handle_remove_decorator(data):
    user_obj, room = _require_room_user()
    if user_obj is None:
        return
    entity_type = str((data or {}).get("entity_type", "")).strip()
    entity_id = str((data or {}).get("entity_id", "")).strip()
    deco_id = str((data or {}).get("deco_id", "")).strip()
    if not entity_type or not entity_id or not deco_id:
        emit("error", {"error": "entity_type, entity_id, and deco_id are required"})
        return
    try:
        canonical_deco_id = decorator_module.normalize_decorator_reference(deco_id)
    except ValueError:
        emit("error", {"error": "invalid decorator reference"})
        return
    entity = _find_room_entity(room, entity_type, entity_id)
    if entity is None:
        emit("error", {"error": f"{entity_type} not found"})
        return
    if hasattr(entity, "decorators") and isinstance(entity.decorators, list):
        entity.decorators = [value for value in entity.decorators if value != canonical_deco_id]
    _broadcast_decorator_update(room, entity, entity_type)


def _emit_inventory_update(user_obj):
    """Emit the current inventory contents to the user's socket."""
    items = []
    for obj in user_obj.peep.inventory.values():
        items.append({
            "obj_id": obj.obj_id,
            "label": obj.label(),
            "description": obj.description(),
            "display": dict(getattr(obj, "_display_assets", {}) or {}),
            "inventory_actions": _inventory_actions_for_object(obj),
        })
    emit("inventory_update", {"items": items}, to=user_obj.sid)
