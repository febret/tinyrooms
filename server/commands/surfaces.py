"""Commands for editing built-in prop surfaces."""

from __future__ import annotations

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand
from server.content.surface_props import sign_options


async def sign_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open the sign editor popup for one sign instance."""

    from server.commands.core import require_room_id

    room_id = require_room_id(context)
    if not command.args:
        raise CommandError("Choose a sign to edit.")
    instance_id = command.args[0]
    try:
        prop = context.rooms.require_prop_target(room_id, instance_id)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    definition = context.world.props[prop.prop_id]
    if definition.render_kind != "sign":
        raise CommandError("That prop is not a sign.")
    surface = context.rooms.surface_for(room_id, prop.id, "sign")
    if surface is None:
        raise CommandError("That sign is not available.")
    return CommandOutcome(
        payload={
            "sign_editor": {
                "room_id": room_id,
                "instance_id": prop.id,
                "surface": surface.serialize(),
                "options": sign_options(),
            }
        },
        toast=False,
        log=False,
    )
