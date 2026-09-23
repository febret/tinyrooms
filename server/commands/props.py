"""Dispenser and crafting-station command handlers."""

from __future__ import annotations

from server.commands.core import require_room_id
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand, parse_target
from server.profiles import InventoryStack
from server.services.crafting import CraftPreview, CraftResult


def _prop_instance_id(token: str) -> str:
    if token.startswith("@"):
        target = parse_target(token)
        if target.kind != "prop":
            raise CommandError("Prop targets must use @prop:<id>.")
        return target.value
    return token


def _craft_binding(context: CommandContext) -> tuple[str, str]:
    activity = context.activities.get(context.account.id)
    if activity is None or activity.kind != "crafting":
        raise CommandError("Open a crafting station first.")
    prop_instance_id = activity.config.get("prop_instance_id")
    if not isinstance(prop_instance_id, str) or not prop_instance_id:
        raise CommandError("That crafting activity is not bound to a station.")
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    return room_id, prop_instance_id


def _serialize_preview(preview: CraftPreview) -> dict[str, object]:
    return {
        "recipe_id": preview.recipe_id,
        "label": preview.label,
        "description": preview.description,
        "energy_cost": preview.energy_cost,
        "ingredients": [
            {
                "card_id": ingredient.card_id,
                "label": ingredient.label,
                "quantity": ingredient.quantity,
                "stacks": [
                    {"stack_id": stack.stack_id, "quantity": stack.quantity, "equipped": stack.equipped}
                    for stack in ingredient.stacks
                ],
            }
            for ingredient in preview.ingredients
        ],
        "output": [
            {"card_id": item.card_id, "label": item.label, "quantity": item.quantity}
            for item in preview.output
        ],
    }


def _serialize_result(result: CraftResult) -> dict[str, object]:
    return {
        "recipe_id": result.recipe_id,
        "label": result.label,
        "outputs": [
            {"card_id": item.card_id, "label": item.label, "quantity": item.quantity}
            for item in result.outputs
        ],
    }


def _mutation_payload(
    context: CommandContext,
    stacks: tuple[InventoryStack, ...],
    **extra: object,
) -> dict[str, object]:
    """Build the shared inventory + refreshed-user payload for a mutation."""

    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return {
        "inventory": [context.cards.serialize_inventory_stack(stack) for stack in stacks],
        "user": context.serialize_user(account),
        **extra,
    }


async def dispense_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Attempt to take a card from a dispenser prop."""

    if not command.args:
        raise CommandError("Choose a dispenser to use.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    result = context.dispensers.dispense(context.account, room_id, prop_instance_id)
    if not result.granted:
        remaining = int(round(result.remaining_seconds))
        raise CommandError(f"That dispenser is recharging for another {remaining}s.")
    return CommandOutcome(
        message=f"Received {result.label}.",
        payload=_mutation_payload(
            context,
            result.stacks,
            dispense={"card_id": result.card_id, "label": result.label, "ready_at": result.ready_at},
        ),
        private_events=[{"type": "toast", "tone": "success", "text": f"You received {result.label}."}],
    )


async def craft_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open the crafting activity bound to a crafting-station prop."""

    if not command.args:
        raise CommandError("Choose a crafting station.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    prop = context.rooms.room_definition(room_id).props.get(prop_instance_id)
    if prop is None:
        raise CommandError("That crafting station is not in this room.")
    if prop.behavior != "crafting":
        raise CommandError("That prop is not a crafting station.")
    if not prop.recipes:
        raise CommandError("That crafting station has no recipes.")
    recipes = []
    for recipe_id in prop.recipes:
        definition = context.recipes.get(recipe_id)
        if definition is None:
            continue
        recipes.append(
            {"id": definition.id, "label": definition.label, "description": definition.description}
        )
    try:
        session, replaced = context.activities.start(
            account_id=context.account.id,
            kind="crafting",
            title="Crafting",
            room_bound=True,
            room_id=room_id,
            replace_existing=False,
            config={"prop_instance_id": prop_instance_id, "recipes": recipes},
        )
    except ValueError as exc:
        raise CommandError(f"{exc} Retry with '.play crafting replace' to replace it.") from exc
    private_events = []
    if replaced is not None:
        private_events.append(
            {"type": "activity.closed", "activity": context.activities.serialize(replaced), "reason": "replaced"}
        )
    private_events.append({"type": "activity.started", "activity": context.activities.serialize(session)})
    return CommandOutcome(
        message="Crafting opened.",
        payload={"activity": context.activities.serialize(session)},
        private_events=private_events,
    )


async def craft_preview_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Preview a recipe for the activity's bound crafting station."""

    if not command.args:
        raise CommandError("Choose a recipe to preview.")
    room_id, prop_instance_id = _craft_binding(context)
    recipe_id = parse_target(command.args[0]).value if command.args[0].startswith("@") else command.args[0]
    preview = context.crafting.preview(context.account, room_id, prop_instance_id, recipe_id)
    return CommandOutcome(message=f"{preview.label} loaded.", payload={"preview": _serialize_preview(preview)})


async def craft_make_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Execute a craft with explicit ingredient stack selections."""

    if len(command.args) < 2:
        raise CommandError("Use '.craft_make <recipe_id> <stack_id>:<quantity> ...'.")
    recipe_id = command.args[0]
    selections: dict[str, int] = {}
    for token in command.args[1:]:
        if ":" not in token:
            raise CommandError("Selections must use <stack_id>:<quantity>.")
        stack_id, raw_quantity = token.rsplit(":", 1)
        try:
            quantity = int(raw_quantity)
        except ValueError as exc:
            raise CommandError("Selection quantities must be integers.") from exc
        selections[stack_id] = quantity
    room_id, prop_instance_id = _craft_binding(context)
    result = context.crafting.craft(
        context.account,
        room_id,
        prop_instance_id,
        recipe_id,
        selections,
    )
    return CommandOutcome(
        message=f"Crafted {result.label or recipe_id}.",
        payload=_mutation_payload(context, result.stacks, craft=_serialize_result(result)),
        private_events=[{"type": "toast", "tone": "success", "text": f"Crafted {result.label or recipe_id}."}],
    )
