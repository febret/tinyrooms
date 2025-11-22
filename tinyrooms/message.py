from typing import NamedTuple

from . import user, actions, room
from .types import ParsedMessage
from .world import active_world
    
    
def parse_message(text: str) -> ParsedMessage:
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
            # TODO: modify to use room context, for now just search in connected users
            search = word[1:]
            if search.startswith('way:'):
                rid = search[4:]
                w = active_world().ways.get(rid, None)
                if w:
                    refs.append(w)
                else:
                    print(f"parse_message: Unknown way reference '{rid}'")
            if search in user.connected_users:
                refs.append(user.connected_users[search])
            else:
                for u in user.connected_users.values():
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