from collections import namedtuple
from pathlib import Path
import random

from flask_socketio import emit
import yaml

from .types import ParsedMessage
from .user import User, connected_users
from .room import Room
from .world import active_world
from .utils import load_defs
from . import text

action_defs = dict()


def load_actions(yaml_path=None):
    """Load action definitions from YAML file or directory."""
    global action_defs
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "data" / "actions"
    # Reload action definitions and refresh connected users
    action_defs = load_defs(
        yaml_path,
        id_key_func=lambda key, value: f"{value['group']}.{key}" if 'group' in value else key
    )
    for u in connected_users.values():
        u.actions_stale = True

    return action_defs


def do_action(action: str, msg: ParsedMessage, user: User, room: Room):
    global action_defs
    global room_table
    if len(action_defs) == 0:
        print("Actions not loaded yet, loading now...")
        load_actions()
    if action in ("basic.look", "look"):
        if len(msg.refs) > 0:
            ref = msg.refs[0]
            desc = ref.info.get('description', "You see nothing special.") if hasattr(ref, 'info') else "You see nothing special."
            emit("message", {"text": f"You look at {text.get_ref_label(ref)}: {desc}"}, to=user.sid)
            emit("activity_panel", {
                "mode": "look",
                "title": f"Looking at {text.get_ref_label(ref)}",
                "content": desc,
            }, to=user.sid)
        else:
            emit("activity_panel", {
                "mode": "look",
                "title": "Look",
                "content": "Select a room entity to inspect.",
            }, to=user.sid)
        return None
    if action in ("basic.equip", "basic.self", "basic.extras"):
        emit("activity_panel", {
            "mode": action.split('.')[-1],
            "title": action.split('.')[-1].title(),
            "content": f"TODO: {action} panel payload is not specified yet.",
        }, to=user.sid)
        return None
    if action is None or len(action) == 0:
        if len(msg.refs) > 0:
            ref = msg.refs[0]
            desc = ref.info.get('description', "You see nothing special.") if hasattr(ref, 'info') else "You see nothing special."
            emit("message", {"text": f"You look at {text.get_ref_label(ref)}: {desc}"}, to=user.sid) 
    elif action == "go":
        way = msg.refs[0]
        to = way.info.get('to')
        if to is None:
            emit("message", {"text": "You can't go that way."}, to=user.sid)
            return None
        if to in active_world().rooms:
            next_room = active_world().rooms[to]
            user.room.remove_user(user) # type: ignore
            next_room.add_user(user)
            emit("message", {"text": f"You go {way.label}."}, to=user.sid)
            emit("message", {"text": f"{user.label} leaves {way.label}."}, room=room.room_id, skip_sid=user.sid)  # type: ignore
            emit("message", {"text": f"{user.label} arrives from {room.label()}."}, room=next_room.room_id, skip_sid=user.sid)  # type: ignore
            return next_room
        else:
            emit("message", {"text": "You can't go that way."}, to=user.sid)
            return None
    elif action in action_defs:    
        act = action_defs[action]
        out_text1, out_text3 = text.make_action_text(
            act,
            user.label,
            msg.refs,
            ' '.join(msg.out_text)
        )
        # Send first and third person messages
        emit("message", {"text": out_text1}, to=user.sid)
        emit("message", {"text": out_text3}, room=user.room.room_id, skip_sid=user.sid)  # type: ignore
        if 'run' in act:
            # If a function with the given name exists in this module, call it
            func_name = act['run']
            func = globals().get(f"{func_name}")
            if callable(func):
                return func(msg, user, room)
            else:
                print(f"do_action: Action '{action}' specifies run='{func_name}' but no such function exists.")
                return None
            
    else: 
        print(f"do_action: Unknown action '{action}' from user '{user.username}'")
        return None
   
