"""Player title commands for customizing the peep label."""

from __future__ import annotations

from server.commands.gameplay import _user_payload
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
)
from server.commands.parser import ParsedCommand


async def title_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Show the current title selection and unlock progress."""

    del command
    payload = context.titles.serialize_for(context.account)
    return CommandOutcome(
        message="Titles loaded.",
        payload={"titles": payload, "user": _user_payload(context)},
    )


async def title_set_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Select (or clear) a title part for one slot."""

    if len(command.args) < 1:
        raise CommandError("Use '.title_set <salutation|nickname|suffix> <title_id|none>'.")
    slot = command.args[0].lower()
    raw_part = command.args[1] if len(command.args) > 1 else "none"
    part_id = None if raw_part.lower() == "none" else raw_part
    try:
        selection = context.titles.set_part(context.account.id, slot, part_id)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    room_id = context.connection.room_id
    broadcasts: list[PendingRoomBroadcast] = []
    if room_id is not None:
        broadcasts.append(
            PendingRoomBroadcast(
                room_id=room_id,
                event={
                    "type": "presence.title",
                    "room_id": room_id,
                    "account_id": account.id,
                    "username": account.username_display,
                    "label": str(selection.get("display_label", account.username_display)),
                },
            )
        )
    return CommandOutcome(
        message="Title updated.",
        payload={"titles": context.titles.serialize_for(account), "user": _user_payload(context)},
        room_broadcasts=broadcasts,
    )


async def title_crew_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Set (or clear) the free-text crew name."""

    raw_name = " ".join(command.args).strip() if command.args else ""
    if raw_name.lower() == "none":
        raw_name = ""
    try:
        selection = context.titles.set_crew_name(context.account.id, raw_name)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    room_id = context.connection.room_id
    broadcasts: list[PendingRoomBroadcast] = []
    if room_id is not None:
        broadcasts.append(
            PendingRoomBroadcast(
                room_id=room_id,
                event={
                    "type": "presence.title",
                    "room_id": room_id,
                    "account_id": account.id,
                    "username": account.username_display,
                    "label": str(selection.get("display_label", account.username_display)),
                },
            )
        )
    return CommandOutcome(
        message="Crew name updated.",
        payload={"titles": context.titles.serialize_for(account), "user": _user_payload(context)},
        room_broadcasts=broadcasts,
    )
