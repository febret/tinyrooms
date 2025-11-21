from collections import namedtuple
from pathlib import Path
import random

from flask_socketio import emit
import yaml

from .types import ParsedMessage
from .user import User, connected_users
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
        ref_text = ref if isinstance(ref, str) else ref.label
        out_text = out_text.replace(f"REF{i+1}", ref_text)
    nothing_txt = ['nothing', 'no one', 'nobody', 'void', 'the ether']
    for n in range(len(msg.refs)+1, 10):
        out_text = out_text.replace(f"REF{n}", random.choice(nothing_txt))
    
    # Replace $* with random tokens from all refs
    if "$*" in out_text:
        # Collect all tokens from all refs
        all_tokens = []
        for ref in msg.refs:
            ref_text = ref if isinstance(ref, str) else ref.label
            all_tokens.extend(ref_text.split())
        
        # If we have tokens, build a random string by picking tokens for each position
        if all_tokens:
            # Count how many words we need (assuming $* represents some number of words)
            # Let's use the total number of tokens as the length
            random_string = ' '.join(random.choice(all_tokens) for _ in range(len(all_tokens)))
            out_text = out_text.replace("$*", random_string)
        else:
            out_text = out_text.replace("$*", "")
    

    # Send first-person text to the user
    out_text1 = f"{action_text[0]} {out_text}"
    emit("message", {"text": out_text1}, to=user.sid)
        
    # Send third-person text to the room
    out_text3 = f"{action_text[1]}:  {out_text}"
    out_text3 = out_text3.replace("USER", user.label)
    emit("message", {"text": out_text3}, room=user.room.room_id, skip_sid=user.sid)  # type: ignore

