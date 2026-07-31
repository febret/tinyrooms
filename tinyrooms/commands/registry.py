from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CommandSpec:
    pattern: str
    power: str | None
    handler: Callable
    summary: str | None = None


COMMANDS: list[CommandSpec] = []


def cmd(pattern: str, power: str | None = None, summary: str | None = None):
    """Decorator that registers a command handler."""

    def decorator(fn: Callable) -> Callable:
        COMMANDS.append(CommandSpec(pattern=pattern, power=power, handler=fn, summary=summary))
        return fn

    return decorator


def pattern_words(pattern: str) -> list[str]:
    return pattern.split()


def matches(tokens: list[str], pattern: str) -> bool:
    words = pattern_words(pattern)
    token_idx = 0
    for word in words:
        if word.startswith("<") and word.endswith(">"):
            if token_idx >= len(tokens):
                return False
            token_idx += 1
        elif word == "...":
            return True
        else:
            if token_idx >= len(tokens):
                return False
            if tokens[token_idx].lower() != word.lower():
                return False
            token_idx += 1
    return token_idx == len(tokens)


def extract_args(tokens: list[str], pattern: str) -> list[str]:
    words = pattern_words(pattern)
    args: list[str] = []
    token_idx = 0
    for word in words:
        if word.startswith("<") and word.endswith(">"):
            if token_idx < len(tokens):
                args.append(tokens[token_idx])
            token_idx += 1
        elif word == "...":
            args.extend(tokens[token_idx:])
            break
        else:
            token_idx += 1
    return args

