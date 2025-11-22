from typing import NamedTuple

from . import actions, room
from .user import connected_users, User
from .room import Room
from .types import ParsedMessage
from .world import active_world


def parse_message(text: str, user: User, room: Room) -> ParsedMessage:
    """Parse a message text into its components."""
    in_text = text.strip()
    out_text = []
    action = ""
    refs = []
    
    # Simple reference parsing: look for @username patterns
    words = in_text.split(' ')
    first = True
    text_ref = False
    chunk = []
    for word in words:
        if first and word.startswith('.'):
            action = word[1:]
        elif word.startswith('.'):
            actid = word[1:]
            if actid in actions.action_defs:
                chunk.append(actions.action_defs[actid].get("description"))
        elif word == '[[@':
            if chunk:
                out_text.append(' '.join(chunk))
                chunk = []
            text_ref = True
        elif word == ']]':
            if text_ref:
                refs.append( ' '.join(chunk))
                chunk = []
            text_ref = False    
        elif word.startswith('@') and len(word) > 1:
            if chunk:
                out_text.append(' '.join(chunk))
                chunk = []
            search = word[1:]
            if search.startswith('way:'):
                rid = search[4:]
                w = active_world().ways.get(rid, None)
                if w:
                    refs.append(w)
                else:
                    print(f"parse_message: Unknown way reference '{rid}'")
            elif search.startswith('obj:'):
                oid = search[4:]
                o = room.objs.get(oid, None)
                if o:
                    refs.append(o)
                else:
                    print(f"parse_message: Unknown object reference '{oid}'")
            if search in room.users:
                refs.append(room.users[search])
            else:
                for u in connected_users.values():
                    if u.username.startswith(search):
                        refs.append(u)
                        break
        else:
            chunk.append(word)
        first = False
    if chunk:
        out_text.append(' '.join(chunk))

    return ParsedMessage(
        in_text=in_text,
        out_text=out_text,
        action=action,
        refs=refs
    )