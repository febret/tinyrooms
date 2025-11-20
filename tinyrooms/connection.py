from flask import request
from flask_socketio import emit
from werkzeug.security import check_password_hash
from tinyrooms import message, user, server, db, room, actions

# Socket.IO events
@server.socketio.on("connect")
def handle_connect():
    print(f"connect: sid={request.sid}")
    emit("connected", {"message": "connected to server"})
    if len(actions.action_defs) == 0:
        actions.load_actions()
    emit("actions_def", {"actions": actions.action_defs}, to=request.sid)



@server.socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    user_obj = user.connected_users.pop(sid, None)
    print(f"disconnect: sid={sid} username={user_obj.username if user_obj else None}")
    if user_obj:
        # Remove user from default room
        user.default_room.remove_user(user_obj.username)
        # broadcast user-left to the room
        user.default_room.send_text(f"{user_obj.username} has left the room", sender_id="system")


@server.socketio.on("login")
def handle_login(data):
    """
    Expect data: {"username": "...", "password": "..."}
    Sends back either:
      - "login_success" with {"username":...}
      - "login_failed" with {"error": "..."}
    """
    sid = request.sid
    username = (data or {}).get("username")
    password = (data or {}).get("password")
    if not username or not password:
        emit("login_failed", {"error": "username and password required"})
        return

    user_row = db.get_user(username)
    if not user_row:
        emit("login_failed", {"error": "invalid credentials"})
        return

    _, password_hash = user_row
    if check_password_hash(password_hash, password):
        # Check if user is already logged in
        if any(u.username == username for u in user.connected_users.values()):
            emit("login_failed", {"error": "user already logged in"})
            print(f"login rejected: {username} is already logged in")
            return
        
        # Create User instance and store it
        user_obj = user.User(username, sid)
        user.connected_users[sid] = user_obj
        
        # Add user to default room
        room.default_room.add_user(user_obj)
        
        emit("login_success", {"username": username})
        
        # Broadcast that a user joined to the room
        room.default_room.send_text(f"{username} has joined the room", sender_id="system")
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
    parsed = message.parse_message(text)
    act = parsed.action or "say"
    actions.do_action(act, parsed, user = user_obj, room = user_obj.room)


# Optional: simple ping from client
@server.socketio.on("ping_server")
def handle_ping(data):
    emit("pong", {"server_time": server.socketio.server.eio.time()})
