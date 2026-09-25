"""Prop marketplace commands used by the Prop Shop activity."""

from __future__ import annotations

from server.commands.activity_launch import resolve_activity, start_activity
from server.commands.core import require_room_id
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand
from server.services.prop_shop import serialize_prop_entry


async def prop_shop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open the Prop Shop marketplace activity."""

    del command
    room_id = require_room_id(context)
    resolved = resolve_activity(context, room_id, "prop-shop")
    return start_activity(context, resolved, room_id=room_id, replace_existing=True)


async def prop_catalog_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Return the full purchasable prop catalog to the shop activity."""

    del command
    catalog = [
        serialize_prop_entry(context.world, definition)
        for definition in context.prop_shop.catalog()
    ]
    return CommandOutcome(message=None, payload={"catalog": catalog}, toast=False, log=False)


async def buy_prop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Spend Bops to permanently unlock a prop."""

    if not command.args:
        raise CommandError("Use '.buy_prop <prop_id>'.")
    result = context.prop_shop.purchase(context.account, command.args[0])
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    if result.replayed:
        message = f"{result.definition.label} is already unlocked."
        events: list[dict[str, object]] = []
    else:
        message = f"Unlocked {result.definition.label} for {result.bops_spent} Bops."
        events = [{"type": "prop.unlocked", "prop_id": result.definition.id}]
    return CommandOutcome(
        message=message,
        payload={
            "unlock": {
                "prop_id": result.definition.id,
                "price": result.definition.price,
                "bops_spent": result.bops_spent,
                "replayed": result.replayed,
            },
            "user": context.serialize_user(account),
        },
        private_events=events,
    )
