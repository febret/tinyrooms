"""Command handlers for signed activity results and records."""

from __future__ import annotations

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand, parse_target


async def activity_start_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Start a paid round for the account's currently open activity."""

    del command
    activity = context.activities.get(context.account.id)
    if activity is None:
        raise CommandError("Open an activity before starting a round.")
    try:
        result = context.activity_results.start(context.account, activity.kind)
        records = context.activity_results.records(context.account.id, activity.kind)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    return CommandOutcome(
        message="Round started.",
        toast=False,
        log=False,
        payload={
            "round": {
                "kind": result.kind,
                "charged": result.charged,
                "energy": result.energy,
            },
            "records": records.to_payload(),
        },
    )


async def activity_records_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Return personal and world records for an activity."""

    if not command.args:
        raise CommandError("Use '.activity_records <kind>'.")
    token = command.args[0]
    kind = parse_target(token).value if token.startswith("@") else token
    try:
        records = context.activity_results.records(context.account.id, kind)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    return CommandOutcome(
        message="Records loaded.",
        toast=False,
        log=False,
        payload={"kind": kind, "records": records.to_payload()},
    )
