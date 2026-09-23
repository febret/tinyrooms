"""Admin console commands with an explicit allowlist and no code execution."""

from __future__ import annotations

import shlex

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand


ALLOWED_ADMIN_COMMANDS = ("help", "status", "rooms", "audit", "say")
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
