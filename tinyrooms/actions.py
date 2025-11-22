from collections import namedtuple
from pathlib import Path
import random

from flask_socketio import emit
import yaml

from .types import ParsedMessage
from .user import User, connected_users
from .room import Room
from . import text

action_defs = dict()


def load_actions(yaml_path=None):
    """Load action definitions from YAML file or directory."""
    global action_defs
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "data" / "actions"
    
    yaml_path = Path(yaml_path)
    action_defs = {}
    
    if yaml_path.is_dir():
        for yaml_file in yaml_path.glob("*.yaml"):
            with open(yaml_file, 'r', encoding='utf-8') as f:
                loaded_actions = yaml.safe_load(f)
                if loaded_actions:
                    for action_key, action_value in loaded_actions.items():
                        if action_key in action_defs:
                            # Clash detected - prepend group name
                            new_key = f"{action_value.get('group', 'default')}.{action_key}"
                            print(f"Warning: Action '{action_key}' from '{yaml_file.name}' clashes with existing action. Renaming to '{new_key}'")
                            action_defs[new_key] = action_value
                        else:
                            action_defs[action_key] = action_value
    elif yaml_path.is_file():
        with open(yaml_path, 'r', encoding='utf-8') as f:
            loaded_actions = yaml.safe_load(f)
            if loaded_actions:
                action_defs.update(loaded_actions)
    else:
        raise FileNotFoundError(f"Path not found: {yaml_path}")
    
    print(f"Loaded {len(action_defs)} actions from {yaml_path}")

    for u in connected_users.values():
        u.actions_stale = True

    return action_defs


def do_action(action: str, msg: ParsedMessage, user: User, room: Room):
    global action_defs
    if len(action_defs) == 0:
        print("Actions not loaded yet, loading now...")
        load_actions()        
    if action not in action_defs:
        return None
       
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

