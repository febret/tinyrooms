"""Multiverse activity commands for discovering and travelling between worlds."""

from __future__ import annotations

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand
from server.commands.travel import departure_outcome


def _friend_stickers(context: CommandContext, world: dict[str, object]) -> list[dict[str, object]]:
    """Resolve the viewer's friends who are online in one world."""

    profile = context.profiles.get_user_profile(context.account.id)
    if profile is None:
        return []
    friend_ids = set(profile.friends)
    online_ids = world.pop("online_account_ids", [])
    if not friend_ids or not isinstance(online_ids, list):
        return []
    matches = [str(account_id) for account_id in online_ids if account_id in friend_ids]
    accounts = context.profiles.get_accounts_by_ids(matches)
    friends: list[dict[str, object]] = []
    for account_id in matches:
        account = accounts.get(account_id)
        if account is None:
            continue
        friends.append(
            {
                "account_id": account.id,
                "username": account.username_display,
                "sticker_url": f"/assets/stickers/{account.sticker}" if account.sticker else "",
            }
        )
    friends.sort(key=lambda entry: str(entry["username"]).casefold())
    return friends


async def multiverse_worlds_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Return the running worlds available to the Multiverse activity."""

    del command
    context.cross_world.check_multiverse_map(context.account)
    worlds = await context.cross_world.list_worlds()
    for world in worlds:
        world["friends"] = _friend_stickers(context, world)
    return CommandOutcome(payload={"worlds": worlds}, toast=False, log=False)


async def multiverse_travel_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Travel to a world selected in the Multiverse activity."""

    if not command.args:
        raise CommandError("Choose a world to visit.")
    world_id = command.args[0].strip()
    if not world_id:
        raise CommandError("Choose a world to visit.")
    if world_id == context.world.id:
        raise CommandError("You are already in that world.")
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    plan = await context.cross_world.prepare_world(context.account, world_id)
    departure = await context.rooms.depart_to_world(
        context.account,
        room_id,
        direction="through the Multiverse",
        destination_room_id=plan.room_id or None,
    )
    payload = context.cross_world.commit(
        context.account,
        plan,
        source_room_id=room_id,
        source_room_label=context.rooms.room_definition(room_id).label,
        source_world_label=context.world.label,
    )
    return departure_outcome(
        context,
        departure,
        payload,
        message="The Multiverse carries you away.",
    )
