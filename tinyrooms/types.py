from typing import NamedTuple


class ParsedEmote(NamedTuple):
    """A single emote invocation extracted from a chat message."""
    emote_id: str
    filename: str        # YAML stem, default 'main'
    refs: list           # target references for this emote
    extra_text: str = '' # plain text payload (used by say emote)


class ParsedMessage(NamedTuple):
    in_text: str
    out_text: list[str]
    refs: list[any]
    emotes: list         # list of ParsedEmote, in order of occurrence
