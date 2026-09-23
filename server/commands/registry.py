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
    usage: str = ""
    power: str | None = None
    help: str = ""
    toast: bool = True
    log: bool = True


class CommandRegistry:
    """Registry of supported normal commands."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(
        self,
        name: str,
        summary: str,
        handler: CommandHandler,
        *,
        usage: str = "",
        power: str | None = None,
        help: str = "",
        toast: bool = True,
        log: bool = True,
    ) -> None:
        """Register a named command with searchable metadata.

        ``toast`` and ``log`` control whether a successful command's generic
        acknowledgement message becomes a transient toast and/or a room activity
        log line. Purely user-facing commands that change nothing in the world
        set both to ``False``.
        """

        self._commands[name] = CommandSpec(
            name=name,
            summary=summary,
            handler=handler,
            usage=usage or f".{name}",
            power=power,
            help=help or summary,
            toast=toast,
            log=log,
        )

    def get(self, name: str) -> CommandSpec | None:
        """Fetch a registered command by name."""

        return self._commands.get(name)

    def list(self) -> list[CommandSpec]:
        """List commands in sorted name order."""

        return [self._commands[name] for name in sorted(self._commands)]

