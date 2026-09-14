"""Command-string parser for normal and reserved admin commands."""

from __future__ import annotations

from dataclasses import dataclass
import shlex


class CommandParseError(ValueError):
    """Raised when a command string is malformed."""


@dataclass(frozen=True, slots=True)
class ParsedTarget:
    """A parsed target token."""

    kind: str
    value: str
    raw: str


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """A parsed command string."""

    kind: str
    name: str
    args: tuple[str, ...]
    raw_text: str


def parse_target(token: str) -> ParsedTarget:
    """Parse a typed target token exactly as designed."""

    raw = token.strip()
    if not raw.startswith("@"):
        raise CommandParseError("Target tokens must start with '@'.")
    if raw.startswith("@card:"):
        return ParsedTarget(kind="card", value=raw[6:], raw=raw)
    if raw.startswith("@prop:"):
        return ParsedTarget(kind="prop", value=raw[6:], raw=raw)
    if raw.startswith("@peep:"):
        return ParsedTarget(kind="peep", value=raw[6:], raw=raw)
    if raw.startswith("@way:"):
        return ParsedTarget(kind="way", value=raw[5:], raw=raw)
    return ParsedTarget(kind="username", value=raw[1:], raw=raw)


def parse_command(text: str) -> ParsedCommand:
    """Parse a user-submitted command or chat string."""

    raw_text = text.strip()
    if not raw_text:
        raise CommandParseError("Command cannot be empty.")
    if raw_text.startswith("\\"):
        return ParsedCommand(kind="admin", name="admin", args=(raw_text[1:].strip(),), raw_text=raw_text)
    if not raw_text.startswith("."):
        return ParsedCommand(kind="normal", name="say", args=(raw_text,), raw_text=raw_text)
    body = raw_text[1:].strip()
    if not body:
        raise CommandParseError("Missing command name.")
    try:
        tokens = shlex.split(body)
    except ValueError as exc:
        raise CommandParseError(str(exc)) from exc
    if not tokens:
        raise CommandParseError("Missing command name.")
    return ParsedCommand(kind="normal", name=tokens[0].lower(), args=tuple(tokens[1:]), raw_text=raw_text)

