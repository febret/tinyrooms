from .user import connected_users, User
from .room import Room
from .types import ParsedMessage, ParsedEmote
from .world import active_world


def _resolve_ref_str(search: str, user_room: Room):
    """Resolve a bare ref string (without the leading '@') to a ref object."""
    if search.startswith('way:'):
        rid = search[4:]
        return active_world().ways.get(rid)
    if search.startswith('obj:'):
        oid = search[4:]
        return user_room.objs.get(oid) if user_room else None
    if search.startswith('prop:'):
        pid = search[5:]
        return user_room.props.get(pid) if user_room else None
    if search.startswith('peep:'):
        pid = search[5:]
        return active_world().peeps.get(pid)
    # Plain username: check room users then connected users
    if user_room and search in user_room.users:
        return user_room.users[search]
    for u in connected_users.values():
        if u.username.startswith(search):
            return u
    return None


def parse_message(text: str, user: User, room: Room) -> ParsedMessage:
    """Parse a chat message into emote invocations and plain text.

    Supported syntax
    ----------------
    - ``[.filename].<emoteId>[@target]`` — emote token (dot-prefixed word).
      ``filename`` defaults to ``main`` when omitted.  An optional ``@target``
      suffix resolves inline.
    - ``@name`` / ``@way:<id>`` / ``@obj:<id>`` / ``@prop:<id>`` /
      ``@peep:<id>`` — standalone reference tokens.
    - ``[[@ … ]]`` — literal text-reference capture (client UI links).

    Plain text that is not part of any emote or reference is collected and
    turned into an implicit ``.say`` emote prepended to the emote list.
    """
    in_text = text.strip()
    words = in_text.split()

    plain_chunks: list[str] = []
    emote_list: list[ParsedEmote] = []
    global_refs: list = []
    chunk: list[str] = []
    text_ref_chunk: list[str] = []
    text_ref = False

    for word in words:
        if word == '[[@':
            if chunk:
                plain_chunks.append(' '.join(chunk))
                chunk = []
            text_ref = True
            text_ref_chunk = []

        elif word == ']]':
            if text_ref:
                global_refs.append(' '.join(text_ref_chunk))
                text_ref_chunk = []
            text_ref = False

        elif text_ref:
            text_ref_chunk.append(word)

        elif word.startswith('.') and len(word) > 1:
            token = word[1:]
            # Split optional inline @target
            if '@' in token:
                dot_part, target_str = token.split('@', 1)
            else:
                dot_part, target_str = token, None

            # Split optional filename prefix: [filename.]emoteId
            if '.' in dot_part:
                filename, emote_id = dot_part.split('.', 1)
            else:
                filename, emote_id = 'main', dot_part

            # Flush plain text accumulated so far
            if chunk:
                plain_chunks.append(' '.join(chunk))
                chunk = []

            # Resolve inline @target for this emote
            emote_refs: list = []
            if target_str:
                ref = _resolve_ref_str(target_str, room)
                if ref is not None:
                    emote_refs.append(ref)
                    global_refs.append(ref)

            emote_list.append(ParsedEmote(emote_id, filename, emote_refs))

        elif word.startswith('@') and len(word) > 1:
            search = word[1:]
            if chunk:
                plain_chunks.append(' '.join(chunk))
                chunk = []
            ref = _resolve_ref_str(search, room)
            if ref is not None:
                global_refs.append(ref)
                # Attach to the most recently parsed emote, if any
                if emote_list:
                    last = emote_list[-1]
                    emote_list[-1] = ParsedEmote(
                        last.emote_id, last.filename,
                        last.refs + [ref], last.extra_text
                    )

        else:
            chunk.append(word)

    if chunk:
        plain_chunks.append(' '.join(chunk))

    plain_text = ' '.join(plain_chunks).strip()

    # Prepend an implicit .say for any plain text
    final_emotes: list[ParsedEmote] = []
    if plain_text:
        final_emotes.append(ParsedEmote('say', 'main', [], plain_text))
    final_emotes.extend(emote_list)

    out_text = [plain_text] if plain_text else []

    return ParsedMessage(
        in_text=in_text,
        out_text=out_text,
        refs=global_refs,
        emotes=final_emotes,
    )
