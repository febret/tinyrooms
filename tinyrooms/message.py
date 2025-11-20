from typing import NamedTuple

from tinyrooms import user


class ParsedMessage(NamedTuple):
    in_text: str
    out_text: list[str]
    action: str
    refs: list[any]
    
    
def parse_message(text: str) -> ParsedMessage:
    """Parse a message text into its components."""
    in_text = text.strip()
    out_text = []
    action = ""
    refs = []
    
    if in_text.startswith('.'):
        parts = in_text.split(' ')
        action = parts[0][1:]  # Remove leading dot
    
    # Simple reference parsing: look for @username patterns
    words = in_text.split(' ')
    first = True
    chunk = []
    for word in words:
        if first and word.startswith('.'):
            action = word[1:]
        elif word.startswith('@') and len(word) > 1:
            if chunk:
                out_text.append(' '.join(chunk))
                chunk = []
            # TODO: modify to use room context, for now just search in connected users
            search = word[1:]
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