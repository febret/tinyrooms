"""Realtor, builder, moderator, and game-master command handlers."""

from __future__ import annotations

from datetime import timedelta
import json
import uuid

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand, parse_target
from server.game.buffs import BuffInstance, TIMED
from server.game.modifiers import clamp_counter
from server.security import utc_now


def _resolve_account(context: CommandContext, token: str):
    username = parse_target(token).value if token.startswith("@") else token
    if username.lower() in {"self", "me"}:
        return context.account
    account = context.profiles.get_account_by_username(username)
    if account is None:
        raise CommandError("That peep could not be found.")
    return account


def _resolve_room_id(context: CommandContext, token: str) -> str:
    room_id = parse_target(token).value if token.startswith("@") else token
    if room_id not in context.rooms.world.rooms:
        raise CommandError("That room does not exist.")
    return room_id


def _resolve_card_id(token: str) -> str:
    if token.startswith("@"):
        target = parse_target(token)
        if target.kind != "card":
            raise CommandError("Card targets must use @card:<id>.")
        return target.value
    return token


async def own_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Realtor room-ownership commands."""

    if len(command.args) < 2:
        raise CommandError("Use '.own <grant|remove|modify|show> <room_id> [@peep]'.")
    action = command.args[0].lower()
    room_id = _resolve_room_id(context, command.args[1])
    if action == "show":
        owner_id = context.ownership.owner_of(room_id)
        owner = context.profiles.get_account_by_id(owner_id) if owner_id else None
        context.audit.safe_record(context.account.id, "realtor.own.show", room_id, "ok")
        message = f"{room_id} is owned by {owner.username_display}." if owner else f"{room_id} has no owner."
        return CommandOutcome(
            message=message,
            payload={"room_id": room_id, "owner_account_id": owner_id, "owner": owner.username_display if owner else None},
        )
    if action == "remove":
        previous = context.ownership.owner_of(room_id)
        context.ownership.revoke(room_id)
        context.audit.safe_record(context.account.id, "realtor.own.remove", room_id, "ok", {"previous": previous})
        return CommandOutcome(message=f"Ownership of {room_id} cleared.", payload={"room_id": room_id, "owner_account_id": None})
    if action not in {"grant", "modify"}:
        raise CommandError("Unknown ownership action.")
    if len(command.args) < 3:
        raise CommandError("Choose a peep to own the room.")
    account = _resolve_account(context, command.args[2])
    if action == "grant":
        context.ownership.grant(room_id, account.id)
        event = "realtor.own.grant"
        message = f"{account.username_display} now owns {room_id}."
    else:
        context.ownership.modify(room_id, account.id)
        event = "realtor.own.modify"
        message = f"{room_id} reassigned to {account.username_display}."
    context.audit.safe_record(context.account.id, event, f"{room_id}:{account.id}", "ok")
    return CommandOutcome(
        message=message,
        payload={"room_id": room_id, "owner_account_id": account.id, "owner": account.username_display},
    )


async def builder_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Builder room/editor commands with an admin-gated grant path."""

    if not command.args:
        raise CommandError("Use '.builder <grant|revoke|rooms> ...'.")
    action = command.args[0].lower()
    if action in {"grant", "revoke"}:
        if not context.powers.has_power(context.account.id, "admin"):
            context.audit.safe_record(context.account.id, f"builder.{action}", None, "rejected", {"reason": "no_admin"})
            raise CommandError("You do not have the admin power here.")
        if len(command.args) < 2:
            raise CommandError("Choose a peep.")
        account = _resolve_account(context, command.args[1])
        if action == "grant":
            context.powers.grant(context.account.id, account.id, "builder")
            message = f"Builder power granted to {account.username_display}."
        else:
            context.powers.revoke(context.account.id, account.id, "builder")
            message = f"Builder power revoked from {account.username_display}."
        return CommandOutcome(message=message, payload={"account_id": account.id})
    if action == "rooms":
        if not context.powers.has_power(context.account.id, "builder"):
            context.audit.safe_record(context.account.id, "builder.rooms", None, "rejected", {"reason": "no_builder"})
            raise CommandError("You do not have the builder power here.")
        rooms = [
            {
                "room_id": room_id,
                "owner_account_id": context.ownership.owner_of(room_id),
                "revision": context.environment.revision(room_id),
            }
            for room_id in sorted(context.rooms.world.rooms)
        ]
        context.audit.safe_record(context.account.id, "builder.rooms", None, "ok")
        return CommandOutcome(message="Room list loaded.", payload={"rooms": rooms})
    raise CommandError("Unknown builder action.")


async def mute_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Moderator mute command."""

    if len(command.args) < 2:
        raise CommandError("Use '.mute @peep <minutes>'.")
    account = _resolve_account(context, command.args[0])
    try:
        minutes = int(command.args[1])
    except ValueError as exc:
        raise CommandError("Mute duration must be an integer number of minutes.") from exc
    if minutes < 1:
        raise CommandError("Mute duration must be at least one minute.")
    until = context.powers.mute(context.account.id, account.id, minutes)
    context.audit.safe_record(context.account.id, "moderation.mute", account.id, "ok", {"minutes": minutes})
    return CommandOutcome(
        message=f"{account.username_display} is muted for {minutes} minutes.",
        payload={"account_id": account.id, "muted_until": until.isoformat()},
    )


async def unmute_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Moderator unmute command."""

    if not command.args:
        raise CommandError("Use '.unmute @peep'.")
    account = _resolve_account(context, command.args[0])
    context.powers.unmute(context.account.id, account.id)
    context.audit.safe_record(context.account.id, "moderation.unmute", account.id, "ok")
    return CommandOutcome(message=f"{account.username_display} is no longer muted.", payload={"account_id": account.id})


async def kick_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Moderator kick: close the target's live connection and broadcast the reason."""

    if not command.args:
        raise CommandError("Use '.kick @peep [reason]'.")
    account = _resolve_account(context, command.args[0])
    reason = " ".join(command.args[1:]).strip() or "You were removed by a moderator."
    connection = await context.connections.get(account.id)
    if connection is None:
        context.audit.safe_record(context.account.id, "moderation.kick", account.id, "rejected", {"reason": "offline"})
        raise CommandError("That peep is not connected.")
    context.audit.safe_record(context.account.id, "moderation.kick", account.id, "ok", {"reason": reason})
    await context.connections.send_session_replaced(connection, f"kicked: {reason}")
    return CommandOutcome(
        message=f"{account.username_display} was removed from the room.",
        payload={"account_id": account.id, "reason": reason},
    )


async def gm_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Game-master gameplay/state commands."""

    if not command.args:
        raise CommandError("Use '.gm <give|setcounter|buff|kudos|environment> ...'.")
    action = command.args[0].lower()
    if action == "give":
        return await _gm_give(context, command)
    if action == "setcounter":
        return await _gm_setcounter(context, command)
    if action == "buff":
        return await _gm_buff(context, command)
    if action == "kudos":
        return await _gm_kudos(context, command)
    if action == "environment":
        return await _gm_environment(context, command)
    raise CommandError("Unknown game-master action.")


async def _gm_give(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 3:
        raise CommandError("Use '.gm give @peep @card:<card_id> [quantity]'.")
    account = _resolve_account(context, command.args[1])
    card_id = _resolve_card_id(command.args[2])
    quantity = 1
    if len(command.args) > 3:
        try:
            quantity = int(command.args[3])
        except ValueError as exc:
            raise CommandError("Quantity must be an integer.") from exc
    if quantity < 1:
        raise CommandError("Quantity must be at least 1.")
    context.inventory.grant(account, card_id, quantity)
    context.audit.safe_record(context.account.id, "gm.give", account.id, "ok", {"card_id": card_id, "quantity": quantity})
    return CommandOutcome(
        message=f"Gave {quantity}× {card_id} to {account.username_display}.",
        payload={"account_id": account.id, "card_id": card_id, "quantity": quantity},
    )


async def _gm_setcounter(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    args = command.args[1:]
    if len(args) == 2:
        account = context.account
        counter, raw_value = args
    elif len(args) >= 3:
        account = _resolve_account(context, args[0])
        counter, raw_value = args[1], args[2]
    else:
        raise CommandError("Use '.gm setcounter [@peep|@self] <counter> <value>'.")
    counter = counter.lower()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise CommandError("Counter value must be a number.") from exc
    snapshot = context.stats.view(account.id)
    maximum = {
        "health": snapshot.effective.max_health,
        "cleanliness": snapshot.effective.max_cleanliness,
        "energy": snapshot.effective.max_energy,
    }.get(counter)
    if maximum is None:
        raise CommandError("Unknown counter.")
    clamped = clamp_counter(value, maximum)
    delta = clamped - getattr(snapshot, counter)
    updated = context.stats.mutate(
        account.id,
        health_delta=delta if counter == "health" else 0.0,
        cleanliness_delta=delta if counter == "cleanliness" else 0.0,
        energy_delta=delta if counter == "energy" else 0.0,
    )
    context.audit.safe_record(context.account.id, "gm.setcounter", account.id, "ok", {"counter": counter, "value": clamped})
    broadcasts = []
    room_id = context.connection.room_id
    if room_id is not None:
        broadcasts.append(
            PendingRoomBroadcast(
                room_id=room_id,
                event={
                    "type": "counter.updated",
                    "room_id": room_id,
                    "target_id": account.id,
                    "target_label": account.username_display,
                    "health_delta": delta if counter == "health" else 0.0,
                    "energy_delta": delta if counter == "energy" else 0.0,
                    "health": updated.health,
                    "energy": updated.energy,
                    "max_health": updated.effective.max_health,
                    "max_energy": updated.effective.max_energy,
                    "statuses": list(updated.statuses),
                    "source_id": context.account.id,
                },
            )
        )
    return CommandOutcome(
        message=f"{counter} set to {clamped:.0f}.",
        payload={"account_id": account.id, "counter": counter, "value": clamped},
        room_broadcasts=broadcasts,
    )


async def _gm_buff(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 4:
        raise CommandError("Use '.gm buff @peep <buff_id> <duration_seconds>'.")
    account = _resolve_account(context, command.args[1])
    buff_id = command.args[2]
    try:
        duration = float(command.args[3])
    except ValueError as exc:
        raise CommandError("Duration must be a number of seconds.") from exc
    if duration <= 0:
        raise CommandError("Duration must be positive.")
    instance = BuffInstance(
        id=buff_id,
        label=buff_id,
        kind=TIMED,
        expires_at=utc_now() + timedelta(seconds=duration),
    )
    context.stats.add_buff(account.id, instance)
    context.audit.safe_record(context.account.id, "gm.buff", account.id, "ok", {"buff_id": buff_id, "duration": duration})
    return CommandOutcome(
        message=f"Applied {buff_id} for {duration:.0f}s.",
        payload={"account_id": account.id, "buff_id": buff_id},
    )


async def _gm_kudos(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 3:
        raise CommandError("Use '.gm kudos @peep <amount>'.")
    account = _resolve_account(context, command.args[1])
    try:
        amount = int(command.args[2])
    except ValueError as exc:
        raise CommandError("Kudos amount must be an integer.") from exc
    context.progression.reward_once(account.id, f"gm:kudos:{uuid.uuid4()}", kudos=amount, kind="gm")
    context.audit.safe_record(context.account.id, "gm.kudos", account.id, "ok", {"amount": amount})
    return CommandOutcome(message=f"Granted {amount} Kudos.", payload={"account_id": account.id, "amount": amount})


async def _gm_environment(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 4:
        raise CommandError("Use '.gm environment <room_id> <key> <json_value>'.")
    room_id = _resolve_room_id(context, command.args[1])
    key = command.args[2]
    try:
        value = json.loads(command.args[3])
    except ValueError as exc:
        raise CommandError("Environment value must be valid JSON.") from exc
    update = context.environment.set(room_id, {key: value})
    context.audit.safe_record(context.account.id, "gm.environment", room_id, "ok", {"key": key})
    return CommandOutcome(
        message=f"Environment '{key}' updated in {room_id}.",
        payload={"room_id": room_id, "revision": update.revision, "environment": update.environment},
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=update.event())],
    )
