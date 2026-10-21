"""Room music command handlers backed by the chiptune.app player."""

from __future__ import annotations

from server.commands.core import require_room_id
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand


MUSIC_POWERS = ("builder", "game-master", "admin")
USAGE = ".music <set <song> [label] | off | reset>"


def _can_control_music(context: CommandContext, room_id: str) -> bool:
    if context.ownership.owner_of(room_id) == context.account.id:
        return True
    return any(context.powers.has_power(context.account.id, power) for power in MUSIC_POWERS)


def _require_music_control(context: CommandContext, room_id: str) -> None:
    if _can_control_music(context, room_id):
        return
    raise CommandError("Only the room owner or staff can change this room's music.")


def _describe(track: dict[str, object] | None) -> str:
    if track is None:
        return "no music"
    label = str(track.get("label") or "").strip()
    song = str(track.get("song") or "").strip()
    return label or song or "unknown track"


async def music_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Set, silence, reset, or report the current room's chiptune.app track."""

    room_id = require_room_id(context)
    args = command.args
    action = args[0].lower() if args else ""

    if not args:
        track = context.music.current(room_id)
        return CommandOutcome(message=f"Room music: {_describe(track)}.", toast=False, log=False)

    if action == "set":
        if len(args) < 2:
            raise CommandError(f"Use '{USAGE}'.")
        _require_music_control(context, room_id)
        song = args[1]
        label = " ".join(args[2:]).strip()
        try:
            event = context.music.set(room_id, song, label=label, updated_by=context.account.username_display)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return CommandOutcome(
            message=f"Room music set to {_describe(event['track'])}.",
            room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
        )

    if action == "off":
        _require_music_control(context, room_id)
        event = context.music.silence(room_id, updated_by=context.account.username_display)
        return CommandOutcome(
            message="Room music turned off.",
            room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
        )

    if action in {"reset", "default"}:
        _require_music_control(context, room_id)
        event = context.music.reset(room_id, updated_by=context.account.username_display)
        return CommandOutcome(
            message=f"Room music reset to {_describe(event['track'])}.",
            room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
        )

    raise CommandError(f"Use '{USAGE}'.")
