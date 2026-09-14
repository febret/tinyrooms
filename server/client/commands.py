"""Client-side command grammar ported from app/js/commands.js."""

from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"\"([^\"\\]|\\.)*\"|'([^'\\]|\\.)*'|[^\s]+")

COMMANDS = [
    {"name": ".help", "summary": "Show common commands."},
    {"name": ".look", "summary": "Describe the current selection."},
    {"name": ".go @way:<id>", "summary": "Move through a room exit."},
    {"name": ".say <text>", "summary": "Speak in the room."},
    {"name": ".inspect @card:<id>", "summary": "Inspect a prop or card."},
    {"name": ".pickup @card:<stack> <qty>", "summary": "Pick up a room stack quantity."},
    {"name": ".drop @card:<stack> <qty>", "summary": "Drop an owned stack quantity."},
    {"name": ".favorite @card:<id>", "summary": "Toggle a favorite core card."},
    {"name": ".play <activity>", "summary": "Open a room or account activity."},
    {"name": ".cancel", "summary": "Cancel targeting or a pending interaction."},
]


def quote(text: str | None) -> str:
    """Quote user-provided text so it survives the command tokenizer."""
    escaped = str(text or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def tokenize(command_text: str | None) -> list[str]:
    """Tokenize the milestone command grammar with single or double quotes."""
    input_text = str(command_text or "").strip()
    if not input_text:
        return []
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(input_text):
        token = match.group(0)
        if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
            tokens.append(re.sub(r"\\([\"'\\])", r"\1", token[1:-1]))
        else:
            tokens.append(token)
    return tokens


def parse_target_token(token: str | None) -> dict[str, str] | None:
    """Parse typed milestone target tokens like @card:stack-1 or @sunbeam."""
    value = str(token or "")
    if not value.startswith("@"):
        return None
    if ":" not in value:
        return {"type": "username", "id": value[1:]}
    parts = value[1:].split(":")
    return {"type": parts[0], "id": ":".join(parts[1:])}


def chat_to_command(input_text: str | None) -> str:
    """Convert chat input into the command-string pipeline expected by the server."""
    text = str(input_text or "").strip()
    if not text:
        return ""
    if text.startswith(".") or text.startswith("\\"):
        return text
    return f".say {quote(text)}"


def build_go_command(way_id: str) -> str:
    """Build a `.go` command for a room exit."""
    return f".go @way:{way_id}"


def build_favorite_command(card_id: str) -> str:
    """Build a `.favorite` command for a core or stack card identifier."""
    return f".favorite @card:{card_id}"


def build_pickup_command(stack_id: str, quantity) -> str:
    """Build a `.pickup` command for a room stack and quantity."""
    return f".pickup @card:{stack_id} {max(1, int(quantity or 1))}"


def build_drop_command(stack_id: str, quantity) -> str:
    """Build a `.drop` command for an owned stack and quantity."""
    return f".drop @card:{stack_id} {max(1, int(quantity or 1))}"


def build_play_command(target_id: str) -> str:
    """Build a `.play` command for an activity or equipped card."""
    return f".play {target_id}"