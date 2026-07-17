from flask import request
from flask_socketio import emit
from werkzeug.security import check_password_hash

from . import message, user, server, db, actions
from .world import active_world

# To send status updates to a client:
# emit("update_status", {"key1": {"label": "Status 1"}, "key2": {"label": "Status 2"}}, to=sid)
#
# To send view updates to a client:
# emit("update_view", {"view": "inventory", "format": "text", "value": "Gold: 100\nItems: 5"}, to=sid)
#
# To change a client's skin:
# user_obj.skin = "base-fantasy"
# user_obj.skin_stale = True
# Or use: user.reload_skins() to reload all users' skins

# Socket.IO events
@server.socketio.on("connect")
def handle_connect():
    print(f"connect: sid={getattr(request, 'sid', None)}")
    emit("connected", {"message": "connected to server"})
    if len(actions.action_defs) == 0:
        actions.load_actions()
    emit("actions_def", {"actions": actions.action_defs}, to=getattr(request, 'sid', None))



@server.socketio.on("disconnect")
def handle_disconnect():
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.pop(sid, None)
    print(f"disconnect: sid={sid} username={user_obj.username if user_obj else None}")
    if user_obj:
        # Save user's state before removing from room
        db.save_user_state(user_obj)
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
    sid = getattr(request, 'sid', None)
    username = (data or {}).get("username")
    password = (data or {}).get("password")
    if not username or not password:
        emit("login_failed", {"error": "username and password required"})
        return

    user_row = db.get_user(username)
    if not user_row:
        emit("login_failed", {"error": "invalid credentials"})
        return

    _, password_hash, saved_skin = user_row
    if check_password_hash(password_hash, password):
        # Check if user is already logged in
        if any(u.username == username for u in user.connected_users.values()):
            emit("login_failed", {"error": "user already logged in"})
            print(f"login rejected: {username} is already logged in")
            return
        
        # Create User instance and store it
        user_obj = user.User(username, sid, active_world())
        # Load saved skin from database
        user_obj.skin = saved_skin or 'base'
        user_obj.skin_stale = True
        user.connected_users[sid] = user_obj
        
        emit("login_success", {"username": username})
        
        print(f"login success: {username} (sid={sid}) - added to default room")
    else:
        emit("login_failed", {"error": "invalid credentials"})


@server.socketio.on("message")
def handle_message(data):
    """
    Expect data: {"text": "..."}
    Only accepts messages if client is authenticated.
    Sends message to the user's current room (default room for now)
    """
    sid = request.sid # type: ignore
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return
    username = user_obj.username
    text = (data or {}).get("text", "").strip()
    if not text:
        return
    parsed = message.parse_message(text, user_obj, user_obj.room)
    act = parsed.action
    if parsed.out_text and len(act) == 0:
        act = "basic.say"
    actions.do_action(act, parsed, user = user_obj, room = user_obj.room)


# Optional: simple ping from client
@server.socketio.on("heartbeat")
def handle_heartbeat(data):
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if user_obj is None:
        return
    if user_obj.actions_stale:
        emit("actions_def", {"actions": actions.action_defs}, to=sid)
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
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"})
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
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"})
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


@server.socketio.on("request_activity_panel")
def handle_request_activity_panel(data):
    sid = getattr(request, 'sid', None)
    user_obj = user.connected_users.get(sid)
    if not user_obj:
        emit("error", {"error": "not authenticated"})
        return
    mode = (data or {}).get("mode", "unknown")
    emit("activity_panel", {
        "mode": mode,
        "title": mode.title(),
        "content": f"TODO: server payload for activity panel mode '{mode}' is not fully specified yet.",
    }, to=sid)