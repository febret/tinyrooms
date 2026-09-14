"""Small command registry used by Tinyrooms command handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


CommandHandler = Callable[..., Awaitable[object]]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Metadata for a registered command handler."""

    name: str
    summary: str
    handler: CommandHandler


class CommandRegistry:
    """Registry of supported normal commands."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, name: str, summary: str, handler: CommandHandler) -> None:
        """Register a named command."""

        self._commands[name] = CommandSpec(name=name, summary=summary, handler=handler)

    def get(self, name: str) -> CommandSpec | None:
        """Fetch a registered command by name."""

        return self._commands.get(name)

    def list(self) -> list[CommandSpec]:
        """List commands in sorted name order."""

        return [self._commands[name] for name in sorted(self._commands)]

