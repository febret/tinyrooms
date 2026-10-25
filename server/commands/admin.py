"""Admin console commands with an explicit allowlist and no code execution."""

from __future__ import annotations

import shlex

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand


ALLOWED_ADMIN_COMMANDS = ("help", "status", "rooms", "audit", "say", "stinky-drop")
BLOCKED_ADMIN_COMMANDS = frozenset({"r", "k"})
BLOCKED_MESSAGE = "The \\r and \\k console commands are not available."


def _tokens(raw: str) -> list[str]:
    try:
        return shlex.split(raw)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc


async def dispatch_admin(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Dispatch an admin console command, requiring the admin power."""

    if not context.powers.has_power(context.account.id, "admin"):
        context.audit.safe_record(context.account.id, "admin.console", None, "rejected", {"reason": "no_admin"})
        raise CommandError("You do not have the admin power here.")
    raw = command.args[0] if command.args else ""
    tokens = _tokens(raw)
    name = tokens[0].lower() if tokens else ""
    if name in BLOCKED_ADMIN_COMMANDS:
        context.audit.safe_record(context.account.id, "admin.console", name or None, "rejected", {"reason": "blocked"})
        raise CommandError(BLOCKED_MESSAGE)
    if name == "help":
        return _admin_help(context)
    if name == "status":
        return await _admin_status(context)
    if name == "rooms":
        return _admin_rooms(context)
    if name == "audit":
        return _admin_audit(context)
    if name == "say":
        return _admin_say(context, tokens[1:])
    if name == "stinky-drop":
        return await _admin_stinky_drop(context, tokens[1:])
    context.audit.safe_record(context.account.id, "admin.console", name or None, "rejected", {"reason": "unknown"})
    raise CommandError(f"Unknown admin command '{name}'. Available: {', '.join(ALLOWED_ADMIN_COMMANDS)}.")


def _admin_help(context: CommandContext) -> CommandOutcome:
    context.audit.safe_record(context.account.id, "admin.help", None, "ok")
    return CommandOutcome(
        message="Admin console commands loaded.",
        payload={
            "commands": [
                {"name": "help", "summary": "List admin console commands."},
                {"name": "status", "summary": "Show world and connection status."},
                {"name": "rooms", "summary": "List rooms in the world."},
                {"name": "audit", "summary": "Show recent audit entries."},
                {"name": "say", "summary": "Broadcast a server announcement."},
                {"name": "stinky-drop", "summary": "Force a stinky drop roll for a room."},
            ]
        },
    )


async def _admin_status(context: CommandContext) -> CommandOutcome:
    online = await context.connections.list_room(context.connection.room_id or "")
    context.audit.safe_record(context.account.id, "admin.status", None, "ok")
    return CommandOutcome(
        message="Server status loaded.",
        payload={
            "world_id": context.rooms.world_id,
            "rooms": len(context.rooms.world.rooms),
            "online_in_room": len(online),
            "account_id": context.account.id,
        },
    )


def _admin_rooms(context: CommandContext) -> CommandOutcome:
    context.audit.safe_record(context.account.id, "admin.rooms", None, "ok")
    rooms = [{"room_id": room_id, "label": room.label} for room_id, room in sorted(context.rooms.world.rooms.items())]
    return CommandOutcome(message="Room list loaded.", payload={"rooms": rooms})


def _admin_audit(context: CommandContext) -> CommandOutcome:
    context.audit.safe_record(context.account.id, "admin.audit", None, "ok")
    return CommandOutcome(message="Audit log loaded.", payload={"entries": context.audit.entries(50)})


def _admin_say(context: CommandContext, words: list[str]) -> CommandOutcome:
    text = " ".join(words).strip()
    if not text:
        raise CommandError("Use '\\say <text>' to announce a message.")
    context.audit.safe_record(context.account.id, "admin.say", None, "ok", {"text": text})
    event = {"type": "chat.message", "speaker_id": None, "speaker": "Server", "style": "spiky", "text": text}
    broadcasts = [
        PendingRoomBroadcast(room_id=room_id, event={"room_id": room_id, **event})
        for room_id in context.rooms.world.rooms
    ]
    return CommandOutcome(message="Announcement sent.", room_broadcasts=broadcasts)


async def _admin_stinky_drop(context: CommandContext, words: list[str]) -> CommandOutcome:
    room_id = words[0] if words else (context.connection.room_id or "")
    if not room_id or room_id not in context.rooms.world.rooms:
        raise CommandError("Use '\\stinky-drop <room>' with a valid room id.")
    if context.card_drops is None:
        raise CommandError("Dynamic card drops are not available in this runtime.")
    occupants = await context.connections.list_room(room_id)
    user_ids = [
        str(getattr(occupant, "account_id", ""))
        for occupant in occupants
        if getattr(occupant, "account_id", None)
    ]
    views = context.stats.views(user_ids)
    stinky = [
        account_id
        for account_id in user_ids
        if views.get(account_id) is not None and "stinky" in views[account_id].statuses
    ]
    if not stinky:
        context.audit.safe_record(context.account.id, "admin.stinky_drop", room_id, "ok", {"dropped": 0})
        return CommandOutcome(message=f"No stinky peeps in {room_id}; nothing dropped.")
    broadcasts = context.card_drops.maybe_drop(room_id, stinky, force=True)
    added = [
        str((broadcast.event.get("stack") or {}).get("definition", {}).get("label") or "?")
        for broadcast in broadcasts
        if broadcast.event.get("type") == "room.card.added"
    ]
    context.audit.safe_record(
        context.account.id, "admin.stinky_drop", room_id, "ok", {"dropped": len(added)}
    )
    if not added:
        return CommandOutcome(
            message=f"Drop roll forced in {room_id} but nothing minted (room may be full).",
            room_broadcasts=broadcasts,
        )
    return CommandOutcome(
        message=f"Dropped {len(added)} card(s) in {room_id}: {', '.join(added)}.",
        room_broadcasts=broadcasts,
    )
