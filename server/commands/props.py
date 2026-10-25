"""Dispenser and crafting-station command handlers."""

from __future__ import annotations

from server.commands.core import require_room_id
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
)
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


def _parse_quantity(args: tuple[str, ...], index: int = 1) -> int:
    if len(args) <= index:
        return 1
    try:
        quantity = int(args[index])
    except ValueError as exc:
        raise CommandError("Quantity must be an integer.") from exc
    if quantity < 1:
        raise CommandError("Quantity must be at least 1.")
    return quantity


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
    context.rooms.require_prop_target(room_id, prop_instance_id)
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
                "image_url": ingredient.image_url,
                "stacks": [
                    {"stack_id": stack.stack_id, "quantity": stack.quantity, "equipped": stack.equipped}
                    for stack in ingredient.stacks
                ],
            }
            for ingredient in preview.ingredients
        ],
        "output": [
            {
                "card_id": item.card_id,
                "label": item.label,
                "quantity": item.quantity,
                "image_url": item.image_url,
            }
            for item in preview.output
        ],
    }


def _serialize_result(result: CraftResult) -> dict[str, object]:
    return {
        "recipe_id": result.recipe_id,
        "label": result.label,
        "outputs": [
            {
                "card_id": item.card_id,
                "label": item.label,
                "quantity": item.quantity,
                "image_url": item.image_url,
            }
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
        "inventory": context.cards.serialize_inventory_stacks(stacks),
        "user": context.serialize_user(account),
        **extra,
    }


async def toggle_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Toggle a prop instance.

    Fixtures are currently the only toggleable kind: flipping one switches
    its light on or off. Anything else is rejected naming the prop.
    """

    if not command.args:
        raise CommandError("Choose something to toggle.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    context.rooms.require_prop_target(room_id, prop_instance_id)
    try:
        event = context.rooms.toggle_prop_light(room_id, prop_instance_id)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    turned_on = bool(((event.get("prop") or {}).get("light") or {}).get("on", True))
    return CommandOutcome(
        payload={"light": {"prop_id": prop_instance_id, "on": turned_on}},
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
        toast=False,
    )


async def open_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open a container prop and return its contents for the client popup."""

    if not command.args:
        raise CommandError("Choose a container to open.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    try:
        contents = context.containers.contents(room_id, prop_instance_id)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    return CommandOutcome(
        payload={"container": contents, "container_open": True}, toast=False, log=False
    )


async def take_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Take cards back out of a container prop into inventory."""

    if len(command.args) < 2:
        raise CommandError("Use '.take @prop:<id> @card:<stack_id> [quantity]'.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    target = parse_target(command.args[1]) if command.args[1].startswith("@") else None
    if target is None or target.kind != "card":
        raise CommandError("Take requires a @card target from the container.")
    quantity = _parse_quantity(command.args, 2)
    try:
        result = context.containers.take(context.account, room_id, prop_instance_id, target.value, quantity)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    return CommandOutcome(
        message=f"Took {result.quantity}× {result.label}.",
        payload=_mutation_payload(
            context,
            result.stacks,
            container=context.containers.contents(room_id, prop_instance_id),
        ),
        private_events=[{"type": "toast", "tone": "success", "text": f"Took {result.label}."}],
    )


async def dispense_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Attempt to take a card from a dispenser prop."""

    if not command.args:
        raise CommandError("Choose a dispenser to use.")
    room_id = require_room_id(context)
    prop_instance_id = _prop_instance_id(command.args[0])
    context.rooms.require_prop_target(room_id, prop_instance_id)
    result = context.dispensers.dispense(context.account, room_id, prop_instance_id)
    if result.all_owned:
        raise CommandError("You already have everything that dispenser offers.")
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
    prop = context.rooms.require_prop_target(room_id, prop_instance_id)
    if context.world.props[prop.prop_id].behavior != "crafting":
        raise CommandError("That prop is not a crafting station.")
    definitions = context.crafting.station_recipes(context.account, room_id, prop_instance_id)
    if not definitions:
        raise CommandError("This station has no recipes you know yet.")
    required_cards = {
        ingredient.card_id
        for definition in definitions
        for ingredient in definition.ingredients
    }
    owned = context.crafting.owned_counts(context.account, required_cards)
    recipes = [
        {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "station": definition.station or "",
            "energy_cost": definition.energy_cost,
            "ingredients": [
                {
                    "card_id": item.card_id,
                    "label": context.cards.definition(item.card_id).label,
                    "quantity": item.quantity,
                    "image_url": context.crafting.image_url(item.card_id),
                    "owned": owned.get(item.card_id, 0),
                }
                for item in definition.ingredients
            ],
            "outputs": [
                {
                    "card_id": item.card_id,
                    "label": context.cards.definition(item.card_id).label,
                    "quantity": item.quantity,
                    "image_url": context.crafting.image_url(item.card_id),
                }
                for item in definition.output
            ],
        }
        for definition in definitions
    ]
    try:
        session, replaced = context.activities.start(
            account_id=context.account.id,
            kind="crafting",
            title="Crafting",
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
    outcome = CommandOutcome(
        message=f"Crafted {result.label or recipe_id}.",
        payload=_mutation_payload(context, result.stacks, craft=_serialize_result(result)),
        private_events=[{"type": "toast", "tone": "success", "text": f"Crafted {result.label or recipe_id}."}],
    )
    recipe = context.recipes.get(result.recipe_id)
    if recipe is not None:
        output_cards = ",".join(output.card_id for output in result.outputs)
        changes = context.tasks.record(
            context.account.id,
            "signal",
            {
                "event": "recipe_crafted",
                "recipe_id": recipe.id,
                "recipe_label": result.label,
                "station": recipe.station or "",
                "source": recipe.source,
                "output_card": output_cards,
            },
        )
        if changes:
            outcome.private_events.append(
                {
                    "type": "task.updated",
                    "tasks": context.tasks.view_payload(context.account.id),
                    "account_id": context.account.id,
                }
            )
            outcome.private_events.extend(
                context.tasks.feedback_events(
                    context.account.id,
                    changes,
                    room_id=room_id,
                )
            )
        for part in context.titles.record_cook(context.account.id):
            outcome.private_events.append(
                {"type": "toast", "tone": "success", "text": f"Title unlocked: {part['label']}."}
            )
        account = context.profiles.get_account_by_id(context.account.id) or context.account
        outcome.payload = {**(outcome.payload or {}), "user": context.serialize_user(account)}
    return outcome
