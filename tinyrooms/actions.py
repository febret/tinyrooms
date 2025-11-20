from collections import namedtuple
from pathlib import Path
import random

from flask_socketio import emit
import yaml

from . import message
from .user import User
from .room import Room

action_defs = dict()

def load_actions(yaml_path=None):
    """Load action definitions from YAML file."""
    global action_defs
    if yaml_path is None:
        # Default path relative to this file
        yaml_path = Path(__file__).parent.parent / "data" / "actions" / "actions.yaml"
    
    with open(yaml_path, 'r', encoding='utf-8') as f:
        action_defs = yaml.safe_load(f)

    emit("actions_def", {"actions": action_defs})

    return action_defs


def do_action(action: str, msg: message.ParsedMessage, user: User, room: Room):
    global action_defs
    if len(action_defs) == 0:
        print("Actions not loaded yet, loading now...")
        load_actions()        
    if action not in action_defs:
        return None
    
    act = action_defs[action]
    action_text = act.get("action_text", [])
    target_text = act.get("target_text", [])
    if isinstance(target_text, str):
        target_text = [target_text]
    end_text = act.get("end_text", [])

    out_text = ""
    if len(msg.refs) > 0 and len(target_text) > 0:
        out_text = target_text[min(len(msg.refs)-1, len(target_text)-1)]
    out_text += ': '
    out_text += ' '.join(msg.out_text) + ' '
    # Pick a random end text
    if len(end_text) > 0:
        out_text += f" {random.choice(end_text)}"
    # Replace all REF placeholders with names of refs in msg, then find any left over
    for i, ref in enumerate(msg.refs):
        out_text = out_text.replace(f"REF{i+1}", ref.label)
    nothing_txt = ['nothing', 'no one', 'nobody', 'void', 'the ether']
    for n in range(len(msg.refs)+1, 10):
        out_text = out_text.replace(f"REF{n}", random.choice(nothing_txt))

    # Send first-person text to the user
    out_text1 = f"{action_text[0]} {out_text}"
    emit("message", {"text": out_text1}, to=user.sid)
        
    # Send second-person text if there is a target and it is a user
    tgt_sid = None
    if len(msg.refs) > 0 and isinstance(msg.refs[0], User):
        out_text2 = f"{action_text[1]} to you: {out_text}"
        out_text2 = out_text2.replace("USER", user.label)
        tgt_sid = msg.refs[0].sid
        emit("message", {"text": out_text2}, to=msg.refs[0].sid)
    
    # Send third-person text to the room
    out_text3 = f"{action_text[1]}:  {out_text}"
    out_text3 = out_text3.replace("USER", user.label)
    print(room.users)
    for u in room.users:
        if u.sid != user.sid and u != tgt_sid:
            emit("message", {"text": out_text3}, to=u.sid)

