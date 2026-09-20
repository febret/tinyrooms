"""Core Milestone 1 command handlers."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.commands.parser import ParsedCommand, parse_target
from server.commands.registry import CommandRegistry
from server.connections import LiveConnection
from server.content.cards import CORE_CARD_IDS
from server.content.worlds import ExitDefinition, PropDefinition, PropInstanceDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.rooms import RoomService
from server.state.world_state import WorldStateRepository


class CommandError(ValueError):
    """Raised when a command is rejected."""


@dataclass(frozen=True, slots=True)
class PendingRoomBroadcast:
    """A room event waiting to be broadcast."""

    room_id: str
    seq: int
    event: dict[str, object]


@dataclass(slots=True)
class CommandOutcome:
    """Result of executing a command handler."""

    message: str | None = None
    code: str | None = None
    payload: dict[str, object] | None = None
    private_events: list[dict[str, object]] = field(default_factory=list)
    room_broadcasts: list[PendingRoomBroadcast] = field(default_factory=list)
    snapshot: dict[str, object] | None = None
    snapshot_seq: int | None = None


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Runtime context passed to command handlers."""

    account: AccountRecord
    connection: LiveConnection
    profiles: ProfileRepository
    world_state: WorldStateRepository
    rooms: RoomService
    cards: CardService
    activities: ActivityService
    registry: CommandRegistry


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


def _require_room_id(context: CommandContext) -> str:
    if context.connection.room_id is None:
        raise CommandError("You are not currently in a room.")
    return context.connection.room_id


def _describe_exit(exit_definition: ExitDefinition) -> dict[str, object]:
    return {
        "kind": "exit",
        "id": exit_definition.id,
        "label": exit_definition.label,
        "description": f"Leads to {exit_definition.target_room_id}.",
        "locked": exit_definition.locked,
    }


def _describe_prop(prop: PropInstanceDefinition, prop_definition: PropDefinition) -> dict[str, object]:
    return {"kind": "prop", "id": prop.id, "label": prop_definition.label, "description": prop_definition.description}


def _entity_outcome(message: str, entity: dict[str, object]) -> CommandOutcome:
    return CommandOutcome(message=message, payload={"entity": entity})


async def help_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    return CommandOutcome(
        message="Command list loaded.",
        payload={
            "commands": [{"name": spec.name, "summary": spec.summary} for spec in context.registry.list()]
        },
    )


async def say_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    message = command.args[0] if command.args else command.raw_text
    seq, event = context.rooms.say(context.account, room_id, message)
    return CommandOutcome(
        message="Message sent.",
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, seq=seq, event=event)],
    )


async def look_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    room = context.rooms.room_definition(room_id)
    if not command.args:
        payload = {
            "entity": {
                "kind": "room",
                "id": room.id,
                "label": room.label,
                "description": room.description,
            }
        }
        return CommandOutcome(message="Room details loaded.", payload=payload)
    target_token = command.args[0]
    if target_token.startswith("@"):
        target = parse_target(target_token)
        if target.kind == "way":
            exit_definition = room.exits.get(target.value)
            if exit_definition is None:
                raise CommandError("That exit is not visible in this room.")
            return _entity_outcome("Exit details loaded.", _describe_exit(exit_definition))
        if target.kind == "card":
            room_stack = next((stack for stack in context.world_state.list_room_cards(room_id) if stack.stack_id == target.value), None)
            if room_stack is not None:
                definition = context.cards.definition(room_stack.card_def_id)
                return _entity_outcome("Card details loaded.", context.cards.serialize_definition(definition))
            inventory_stack = context.profiles.get_inventory_stack(context.account.id, context.rooms.world_id, target.value)
            if inventory_stack is None:
                raise CommandError("That card is not visible right now.")
            definition = context.cards.definition(inventory_stack.card_def_id)
            return _entity_outcome("Card details loaded.", context.cards.serialize_definition(definition))
        if target.kind == "prop":
            prop = room.props.get(target.value)
            if prop is None:
                raise CommandError("That prop is not in this room.")
            prop_definition = context.rooms.prop_definition(prop.prop_id)
            return _entity_outcome("Prop details loaded.", _describe_prop(prop, prop_definition))
        if target.kind in {"peep", "username"}:
            for occupant in await context.rooms.room_occupants(room_id):
                if target.kind == "peep" and occupant["id"] == target.value:
                    return _entity_outcome("Peep details loaded.", occupant)
                if target.kind == "username" and str(occupant["username"]).casefold() == target.value.casefold():
                    return _entity_outcome("Peep details loaded.", occupant)
            for peep in context.rooms.room_peeps(room_id):
                if target.kind == "peep" and peep["id"] == target.value:
                    return _entity_outcome("Peep details loaded.", peep)
                if target.kind == "username" and str(peep["label"]).casefold() == target.value.casefold():
                    return _entity_outcome("Peep details loaded.", peep)
            raise CommandError("That peep is not in this room.")
    if target_token in room.exits:
        return _entity_outcome("Exit details loaded.", _describe_exit(room.exits[target_token]))
    if target_token in room.props:
        prop = room.props[target_token]
        prop_definition = context.rooms.prop_definition(prop.prop_id)
        return _entity_outcome("Prop details loaded.", _describe_prop(prop, prop_definition))
    raise CommandError("That target is not visible right now.")


async def inspect_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    return await look_command(context, command)


async def go_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    if not command.args:
        raise CommandError("Choose an exit to use.")
    exit_token = command.args[0]
    exit_id = parse_target(exit_token).value if exit_token.startswith("@") else exit_token
    navigation = await context.rooms.navigate(context.account, room_id, exit_id)
    outcome = CommandOutcome(
        message=f"You moved to {navigation.destination_room_id}.",
        payload={"room_id": navigation.destination_room_id},
        snapshot=navigation.destination_snapshot,
        snapshot_seq=navigation.destination_snapshot_seq,
    )
    outcome.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=navigation.source_room_id,
            seq=navigation.source_seq,
            event=navigation.source_event,
        )
    )
    outcome.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=navigation.destination_room_id,
            seq=navigation.destination_seq,
            event=navigation.destination_event,
        )
    )
    if navigation.closed_activity is not None:
        outcome.private_events.append({"type": "activity.closed", "activity": navigation.closed_activity, "reason": "room_changed"})
    return outcome


async def pickup_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    if not command.args:
        raise CommandError("Choose a room card to pick up.")
    target = parse_target(command.args[0]) if command.args[0].startswith("@") else None
    if target is None or target.kind != "card":
        raise CommandError("Pickup requires a @card target.")
    quantity = _parse_quantity(command.args)
    mutation = context.cards.pickup(context.account, room_id, target.value, quantity)
    return CommandOutcome(
        message="Card picked up.",
        payload={"inventory": mutation.inventory},
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, seq=mutation.room_seq, event=mutation.room_event)],
    )


async def drop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    if not command.args:
        raise CommandError("Choose an inventory card to drop.")
    target = parse_target(command.args[0]) if command.args[0].startswith("@") else None
    if target is None or target.kind != "card":
        raise CommandError("Drop requires a @card target.")
    quantity = _parse_quantity(command.args)
    mutation = context.cards.drop(context.account, room_id, target.value, quantity, pos=(50.0, 50.0, 0.0))
    return CommandOutcome(
        message="Card dropped.",
        payload={"inventory": mutation.inventory},
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, seq=mutation.room_seq, event=mutation.room_event)],
    )


async def reset_room_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    # TODO(Milestone 2): restrict .reset_room to admins once user roles exist.
    if command.args:
        raise CommandError("Use '.reset_room' with no arguments from inside the room to reset.")
    room_id = _require_room_id(context)
    room = context.rooms.room_definition(room_id)
    stacks, seq = context.world_state.reset_room_cards(room_id, room.initial_cards)
    serialized = [context.cards.serialize_room_stack(stack) for stack in stacks]
    snapshot = await context.rooms.build_snapshot(context.account, room_id)
    return CommandOutcome(
        message="Room reset to its defined state.",
        payload={"room_cards": serialized},
        room_broadcasts=[
            PendingRoomBroadcast(
                room_id=room_id,
                seq=seq,
                event={
                    "type": "room.cards.reset",
                    "room_id": room_id,
                    "stacks": serialized,
                    "reset_by": context.account.username_display,
                },
            )
        ],
        snapshot=snapshot,
        snapshot_seq=seq,
    )


async def favorite_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a core card to favorite.")
    target = command.args[0]
    if target.startswith("@"):
        parsed = parse_target(target)
        if parsed.kind != "card":
            raise CommandError("Favorite expects a core card ID.")
        target = parsed.value
    if target not in CORE_CARD_IDS:
        raise CommandError("Only core cards can be favorited in Milestone 1.")
    payload = context.cards.toggle_favorite(context.account, target)
    return CommandOutcome(message="Favorites updated.", payload=payload)


async def settings_command(
    context: CommandContext,
    command: ParsedCommand,
) -> CommandOutcome:
    if len(command.args) != 2 or command.args[0].lower() != "action-log":
        raise CommandError("Use '.settings action-log on' or '.settings action-log off'.")
    value = command.args[1].lower()
    if value not in {"on", "off"}:
        raise CommandError("Action Log setting must be 'on' or 'off'.")
    account = context.profiles.set_show_activity_log(
        context.account.id,
        value == "on",
    )
    return CommandOutcome(
        message=f"Action Log turned {value}.",
        payload={"show_activity_log": account.show_activity_log},
    )


async def play_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = _require_room_id(context)
    if not command.args:
        raise CommandError("Choose an activity to play.")
    target = command.args[0].lower()
    replace_existing = any(arg.lower() in {"replace", "--replace"} for arg in command.args[1:])
    if target == "molly":
        if room_id != "playroom":
            raise CommandError("Molly is only available in the Playroom.")
        kind = "lazor-rush"
        title = "Lazor Rush"
    elif target in {"lazor-rush", "shop", "crafting"}:
        kind = target
        title = target.replace("-", " ").title()
    elif target == "sample":
        if not context.activities.developer_sample_enabled:
            raise CommandError("The developer sample activity is not enabled.")
        kind = "dev-sample"
        title = "Sample Activity"
    else:
        raise CommandError("Unknown activity.")
    try:
        session, replaced = context.activities.start(
            account_id=context.account.id,
            kind=kind,
            title=title,
            room_bound=kind != "sticker-designer",
            room_id=room_id,
            replace_existing=replace_existing,
        )
    except ValueError as exc:
        raise CommandError(f"{exc} Retry with '.play {target} replace' to replace it.") from exc
    private_events = []
    if replaced is not None:
        private_events.append({"type": "activity.closed", "activity": context.activities.serialize(replaced), "reason": "replaced"})
    private_events.append({"type": "activity.started", "activity": context.activities.serialize(session)})
    return CommandOutcome(
        message=f"{title} opened.",
        payload={"activity": context.activities.serialize(session)},
        private_events=private_events,
    )


async def cancel_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    current = context.activities.close(context.account.id)
    if current is None:
        raise CommandError("No activity is currently open.")
    return CommandOutcome(
        message="Activity closed.",
        payload={"activity": None},
        private_events=[{"type": "activity.closed", "activity": context.activities.serialize(current), "reason": "cancelled"}],
    )


def build_registry() -> CommandRegistry:
    """Build the Milestone 1 command registry."""

    registry = CommandRegistry()
    registry.register("cancel", "Close the active activity window.", cancel_command)
    registry.register("drop", "Drop a quantity from one of your inventory stacks.", drop_command)
    registry.register("favorite", "Toggle a favorite core card.", favorite_command)
    registry.register("go", "Move through an exit in the current room.", go_command)
    registry.register("help", "Show the available commands.", help_command)
    registry.register("inspect", "Inspect a visible room entity.", inspect_command)
    registry.register("look", "Look at the room or a visible entity.", look_command)
    registry.register("pickup", "Pick up a room card stack quantity.", pickup_command)
    registry.register("play", "Open a room activity or developer sample activity.", play_command)
    registry.register("reset_room", "Reset the current room's cards to the world definition.", reset_room_command)
    registry.register("say", "Send a room-scoped chat message.", say_command)
    registry.register(
        "settings",
        "Change a persisted client setting.",
        settings_command,
    )
    return registry


async def dispatch_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Dispatch a parsed normal command through the registry."""

    if command.kind == "admin":
        raise CommandError("Admin console commands are reserved and not enabled yet.")
    spec = context.registry.get(command.name)
    if spec is None:
        raise CommandError(f"Unknown command '.{command.name}'.")
    return await spec.handler(context, command)
