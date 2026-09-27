"""The ``.cutscene`` command and shared cutscene launch helpers.

This module deliberately does not import ``server.commands.core``: the registry
in core imports the handler from here, so the room lookup is resolved locally
instead of creating an import cycle.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand, parse_target
from server.content.common import ContentError
from server.content.cutscenes import CutsceneDefinition, parse_param_arguments
from server.services.cutscenes import (
    AUDIENCE_PRIVATE,
    AUDIENCE_ROOM,
    CutsceneError,
    CutsceneLaunch,
    choose_audience,
)

PRIVATE_FLAG = "--private"
ROOM_FLAG = "--room"
PLACEHOLDER_KEYS = {"prop": "prop", "peep": "peep"}


def _current_room(context: CommandContext) -> str:
    """Return the caller's room, rejecting the command when they have none."""

    if context.connection.room_id is None:
        raise CommandError("You are not currently in a room.")
    return context.connection.room_id


def resolve_cutscene(context: CommandContext, reference: str) -> CutsceneDefinition:
    """Resolve a cutscene reference, converting service errors for the player."""

    try:
        return context.cutscenes.resolve(reference)
    except CutsceneError as exc:
        raise CommandError(str(exc)) from exc


def check_cutscene(context: CommandContext, definition: CutsceneDefinition, room_id: str) -> None:
    """Validate a definition against the room and the caller's powers."""

    try:
        context.cutscenes.check(definition, room_id=room_id, has_power=context.powers.has_power)
    except CutsceneError as exc:
        raise CommandError(str(exc)) from exc


async def room_occupants(context: CommandContext, room_id: str) -> tuple[str, ...]:
    """Return the account ids currently in a room."""

    return tuple(connection.account_id for connection in await context.connections.list_room(room_id))


async def build_launch(
    context: CommandContext,
    *,
    definition: CutsceneDefinition,
    room_id: str,
    audience: str,
    origin: str,
    params: dict[str, object] | None = None,
) -> CutsceneLaunch:
    """Validate and build a cutscene launch, charging any configured energy."""

    check_cutscene(context, definition, room_id)
    if definition.energy_cost:
        context.stats.charge(context.account, definition.energy_cost)
    return context.cutscenes.launch(
        definition=definition,
        account=context.account,
        room_id=room_id,
        audience=audience,
        origin=origin,
        params=params,
        occupants=await room_occupants(context, room_id),
    )


def deliver(launch: CutsceneLaunch) -> tuple[list[dict[str, object]], list[PendingRoomBroadcast]]:
    """Split a launch into private events or a room broadcast."""

    if launch.is_room_wide:
        return [], [PendingRoomBroadcast(room_id=launch.room_id, event=launch.event)]
    return [launch.event], []


def split_arguments(
    args: Iterable[str],
) -> tuple[str | None, str | None, str | None, list[str]]:
    """Split a reference, audience flag, target token, and key=value pairs."""

    reference: str | None = None
    audience: str | None = None
    target: str | None = None
    overrides: list[str] = []
    for arg in args:
        if arg == ROOM_FLAG:
            audience = AUDIENCE_ROOM
        elif arg == PRIVATE_FLAG:
            audience = AUDIENCE_PRIVATE
        elif arg.startswith("@"):
            target = arg
        elif reference is None:
            reference = arg
        else:
            overrides.append(arg)
    return reference, audience, target, overrides


def placeholders_for_target(target: str | None) -> dict[str, str]:
    """Return the placeholder a prop or peep target implies."""

    if not target:
        return {}
    parsed = parse_target(target)
    if parsed.kind in PLACEHOLDER_KEYS:
        return {parsed.kind: f"${parsed.kind}:{parsed.value}"}
    return {}


def origin_for_target(target: str | None) -> str:
    """Return the origin label implied by a target token."""

    if not target:
        return "command"
    kind = parse_target(target).kind
    return kind if kind in PLACEHOLDER_KEYS else "command"


def resolve_audience(definition: CutsceneDefinition, requested: str | None) -> str:
    """Choose the delivery audience, converting service errors for the player."""

    try:
        return choose_audience(definition, requested)
    except CutsceneError as exc:
        raise CommandError(str(exc)) from exc


async def play_cutscene(
    context: CommandContext,
    *,
    reference: str,
    room_id: str,
    audience: str | None = None,
    target: str | None = None,
    params: dict[str, object] | None = None,
    origin: str | None = None,
) -> CutsceneLaunch:
    """Resolve, validate, and build one cutscene launch for the caller.

    *params* is already a mapping of validated scalars; a target token
    contributes its own placeholder on top.
    """

    definition = resolve_cutscene(context, reference)
    merged = {**(params or {}), **placeholders_for_target(target)}
    return await build_launch(
        context,
        definition=definition,
        room_id=room_id,
        audience=resolve_audience(definition, audience),
        origin=origin or origin_for_target(target),
        params=merged,
    )


async def cutscene_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Play a cutscene for the caller, or for the whole room with ``--room``."""

    if not command.args:
        raise CommandError("Usage: .cutscene <id> [key=value ...] [@prop:|@peep:] [--room]")
    reference, audience, target, overrides = split_arguments(command.args)
    if not reference or reference.startswith("-"):
        raise CommandError("Choose a cutscene to play.")
    room_id = _current_room(context)
    try:
        params = parse_param_arguments(overrides)
    except ContentError as exc:
        raise CommandError(str(exc)) from exc
    launch = await play_cutscene(
        context,
        reference=reference,
        room_id=room_id,
        audience=audience,
        target=target,
        params=params,
    )
    private_events, room_broadcasts = deliver(launch)
    scope = "the room" if launch.is_room_wide else "you"
    return CommandOutcome(
        message=f"{launch.definition.title} played for {scope}.",
        private_events=private_events,
        room_broadcasts=room_broadcasts,
        toast=False,
    )
