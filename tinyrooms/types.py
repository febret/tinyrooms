from typing import NamedTuple


class ParsedMessage(NamedTuple):
    in_text: str
    out_text: list[str]
    action: str
    refs: list[any]
