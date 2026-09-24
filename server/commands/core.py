"""Core Milestone 1 command handlers."""

from __future__ import annotations

import math

from server.behaviors.events import BehaviorEvent, PeepRef, PropRef
from server.commands.activity_launch import resolve_activity, start_activity
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
)
from server.commands.parser import ParsedCommand, parse_target
from server.commands.registry import CommandRegistry
from server.content.worlds import ExitDefinition, PropDefinition, PropInstanceDefinition


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


def _parse_drop_position(args: tuple[str, ...]) -> tuple[float, float, float]:
    coordinates = [50.0, 50.0, 0.0]
    for index in range(3):
        argument_index = 2 + index
        if len(args) <= argument_index:
            break
        try:
            coordinates[index] = float(args[argument_index])
        except ValueError as exc:
            raise CommandError("Drop position coordinates must be numbers.") from exc
    if not all(math.isfinite(value) for value in coordinates):
        raise CommandError("Drop position coordinates must be finite numbers.")
    return (
        min(100.0, max(0.0, coordinates[0])),
        min(100.0, max(0.0, coordinates[1])),
        min(50.0, max(0.0, coordinates[2])),
    )


def require_room_id(context: CommandContext) -> str:
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


def _merge_behavior(outcome: CommandOutcome, result: object | None) -> None:
    if result is None:
        return
    outcome.private_events.extend(getattr(result, "private_events", []))
    outcome.room_broadcasts.extend(getattr(result, "room_broadcasts", []))
    for message in getattr(result, "messages", []):
        if message and not outcome.message:
            outcome.message = message


async def _resolve_peep_ref(context: CommandContext, token: str) -> PeepRef:
    room_id = require_room_id(context)
    parsed = parse_target(token) if token.startswith("@") else None
    kind = parsed.kind if parsed else "username"
    value = parsed.value if parsed else token
    for peep in context.rooms.room_peeps(room_id):
        peep_id = str(peep["id"])
        if (kind == "peep" and peep_id == value) or (
            kind == "username"
            and (str(peep["label"]).casefold() == value.casefold() or peep_id == value)
        ):
            return PeepRef(kind="npc", peep_id=peep_id, account_id=None)
    for occupant in await context.rooms.room_occupants(room_id):
        if (kind == "peep" and occupant["id"] == value) or (
            kind == "username" and str(occupant["username"]).casefold() == value.casefold()
        ):
            return PeepRef(kind="user", peep_id=None, account_id=str(occupant["id"]))
    raise CommandError("That peep is not in this room.")


async def _resolve_action_target(context: CommandContext, token: str) -> PeepRef | PropRef:
    parsed = parse_target(token) if token.startswith("@") else None
    if parsed is not None and parsed.kind == "prop":
        room_id = require_room_id(context)
        prop = context.rooms.room_definition(room_id).props.get(parsed.value)
        if prop is None:
            raise CommandError("That prop is not in this room.")
        return PropRef(instance_id=prop.id, prop_id=prop.prop_id, room_id=room_id)
    return await _resolve_peep_ref(context, token)


async def help_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    commands = [
        {
            "name": spec.name,
            "summary": spec.summary,
            "usage": spec.usage,
            "power": spec.power,
            "help": spec.help,
        }
        for spec in context.registry.list()
    ]
    return CommandOutcome(message="Command list loaded.", payload={"commands": commands})


async def say_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if context.powers.is_muted(context.account.id):
        raise CommandError("You are muted and cannot chat right now.")
    room_id = require_room_id(context)
    message = command.args[0] if command.args else command.raw_text
    event = context.rooms.say(context.account, room_id, message)
    return CommandOutcome(
        message="Message sent.",
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
    )


async def look_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
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
    room_id = require_room_id(context)
    if not command.args:
        raise CommandError("Choose an exit to use.")
    exit_token = command.args[0]
    exit_id = parse_target(exit_token).value if exit_token.startswith("@") else exit_token
    navigation = await context.rooms.navigate(context.account, room_id, exit_id)
    context.tasks.record(
        context.account.id,
        "go",
        {"exit_id": exit_id, "room_id": navigation.destination_room_id},
    )
    outcome = CommandOutcome(
        message=f"You moved to {navigation.destination_room_id}.",
        payload={"room_id": navigation.destination_room_id},
        snapshot=navigation.destination_snapshot,
    )
    outcome.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=navigation.source_room_id,
            event=navigation.source_event,
        )
    )
    outcome.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=navigation.destination_room_id,
            event=navigation.destination_event,
        )
    )
    if navigation.closed_activity is not None:
        outcome.private_events.append({"type": "activity.closed", "activity": navigation.closed_activity, "reason": "room_changed"})
    for behavior in navigation.behavior_results:
        _merge_behavior(outcome, behavior)
    return outcome


async def talk_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
    if not command.args:
        raise CommandError("Choose a peep to talk to.")
    ref = await _resolve_peep_ref(context, command.args[0])
    if ref.kind != "npc" or not ref.peep_id:
        raise CommandError("That peep has nothing to say.")
    context.dialogs.start(context.account, ref.peep_id)
    behavior = await context.behaviors.dispatch(
        BehaviorEvent(
            type="quick_action",
            actor=PeepRef(kind="user", peep_id=None, account_id=context.account.id),
            target=ref,
            room_id=room_id,
            action="talk",
            data={},
        )
    )
    outcome = CommandOutcome(
        message="Conversation started.",
        payload={"dialog": context.dialogs.serialize(context.dialogs.view(context.account.id))},
    )
    _merge_behavior(outcome, behavior)
    return outcome

async def act_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
    if len(command.args) < 2:
        raise CommandError("Use '.act <action> <target>'.")
    action = command.args[0].strip().lower()
    if not action:
        raise CommandError("Choose an action to perform.")
    target = await _resolve_action_target(context, command.args[1])
    behavior = await context.behaviors.dispatch(
        BehaviorEvent(
            type="quick_action",
            actor=PeepRef(kind="user", peep_id=None, account_id=context.account.id),
            target=target,
            room_id=room_id,
            action=action,
            data={},
        )
    )
    outcome = CommandOutcome()
    _merge_behavior(outcome, behavior)
    if not outcome.message:
        outcome.message = f"You {action}."
    return outcome


async def dialog_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a dialog option.")
    try:
        index = int(command.args[0])
    except ValueError as exc:
        raise CommandError("Dialog choice must be an index.") from exc
    result = await context.dialogs.choose(context.account, index)
    outcome = CommandOutcome(message="Conversation updated.", payload={"dialog": result.dialog})
    _merge_behavior(outcome, result.behavior_result)
    outcome.private_events.extend(result.events)
    return outcome


async def dialog_end_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    context.dialogs.end(context.account.id, "user")
    return CommandOutcome(message="Conversation ended.", payload={"dialog": None})


async def pickup_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
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
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=mutation.room_event)],
    )


async def drop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
    if not command.args:
        raise CommandError("Choose an inventory card to drop.")
    target = parse_target(command.args[0]) if command.args[0].startswith("@") else None
    if target is None or target.kind != "card":
        raise CommandError("Drop requires a @card target.")
    quantity = _parse_quantity(command.args)
    position = _parse_drop_position(command.args)
    mutation = context.cards.drop(context.account, room_id, target.value, quantity, pos=position)
    return CommandOutcome(
        message="Card dropped.",
        payload={"inventory": mutation.inventory},
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=mutation.room_event)],
    )


async def reset_room_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    # TODO(Milestone 2): restrict .reset_room to admins once user roles exist.
    if command.args:
        raise CommandError("Use '.reset_room' with no arguments from inside the room to reset.")
    room_id = require_room_id(context)
    room = context.rooms.room_definition(room_id)
    stacks = context.world_state.reset_room_cards(room_id, room.initial_cards)
    serialized = [context.cards.serialize_room_stack(stack) for stack in stacks]
    snapshot = await context.rooms.build_snapshot(context.account, room_id)
    return CommandOutcome(
        message="Room reset to its defined state.",
        room_broadcasts=[
            PendingRoomBroadcast(
                room_id=room_id,
                event={
                    "type": "room.cards.reset",
                    "room_id": room_id,
                    "stacks": serialized,
                    "reset_by": context.account.username_display,
                },
            )
        ],
        snapshot=snapshot,
    )


async def settings_command(
    context: CommandContext,
    command: ParsedCommand,
) -> CommandOutcome:
    if len(command.args) != 2 or command.args[0].lower() != "action-log":
        raise CommandError("Use '.settings action-log on' or '.settings action-log off'.")
    value = command.args[1].lower()
    if value not in {"on", "off"}:
        raise CommandError("Action Log setting must be 'on' or 'off'.")
    user_profile = context.profiles.set_show_activity_log(
        context.account.id,
        value == "on",
    )
    return CommandOutcome(
        message=f"Action Log turned {value}.",
        payload={"show_activity_log": user_profile.show_activity_log},
    )


async def play_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = require_room_id(context)
    if not command.args:
        raise CommandError("Choose an activity to play.")
    target = command.args[0]
    replace_existing = any(arg.lower() in {"replace", "--replace"} for arg in command.args[1:])
    resolved = resolve_activity(context, room_id, target)
    return start_activity(
        context,
        resolved,
        room_id=room_id,
        replace_existing=replace_existing,
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


def _memory_text(command: ParsedCommand) -> str:
    parts = command.raw_text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _memory_target(command: ParsedCommand) -> str:
    if not command.args:
        raise CommandError("Choose a memory with @memory:<id>.")
    target = parse_target(command.args[0])
    if target.kind != "memory":
        raise CommandError("Memory targets must use @memory:<id>.")
    return target.value


async def tasks_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    return CommandOutcome(
        message="Task list loaded.",
        payload={"tasks": context.tasks.view_payload(context.account.id)},
    )


async def task_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a task with '.task <task_id>'.")
    token = command.args[0]
    task_id = parse_target(token).value if token.startswith("@") else token
    view = context.tasks.view(context.account.id, task_id)
    if view is None:
        raise CommandError("That task is not available.")
    return CommandOutcome(
        message=f"{view['title']} loaded.",
        payload={"task": view, "tasks": context.tasks.view_payload(context.account.id)},
    )


async def memories_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if command.args and len(command.args) != 2:
        raise CommandError("Use '.memories' or '.memories <year> <month>'.")
    if command.args:
        try:
            year = int(command.args[0])
            month = int(command.args[1])
        except ValueError as exc:
            raise CommandError("Year and month must be integers.") from exc
        if not 1 <= month <= 12:
            raise CommandError("Month must be between 1 and 12.")
    else:
        year, month = context.memories.current_year_month()
    journal = context.memories.journal_payload(context.account.id, year, month)
    return CommandOutcome(message="Memories loaded.", payload={"journal": journal})


async def memory_new_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    memory = context.memories.create_manual(context.account.id, _memory_text(command))
    year, month = context.memories.local_month_of(memory.created_at) or context.memories.current_year_month()
    return CommandOutcome(
        message="Memory saved.",
        payload={"journal": context.memories.journal_payload(context.account.id, year, month)},
        private_events=[{"type": "toast", "tone": "success", "text": "Memory saved."}],
    )


async def memory_edit_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    memory_id = _memory_target(command)
    cursor = command.raw_text.find(command.args[0])
    text = command.raw_text[cursor + len(command.args[0]):].strip()
    memory = context.memories.edit_manual(context.account.id, memory_id, text)
    year, month = context.memories.local_month_of(memory.created_at) or context.memories.current_year_month()
    return CommandOutcome(
        message="Memory updated.",
        payload={"journal": context.memories.journal_payload(context.account.id, year, month)},
    )


async def memory_delete_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    memory_id = _memory_target(command)
    context.memories.delete_manual(context.account.id, memory_id)
    year, month = context.memories.current_year_month()
    return CommandOutcome(
        message="Memory deleted.",
        payload={"journal": context.memories.journal_payload(context.account.id, year, month)},
        private_events=[{"type": "toast", "tone": "success", "text": "Memory deleted."}],
    )


def build_registry() -> CommandRegistry:
    """Build the command registry."""

    from server.commands import activity_hooks, gameplay, privileged, props

    registry = CommandRegistry()
    registry.register(
        "act",
        "Dispatch a quick action to a target peep or prop.",
        act_command,
        usage=".act <action> <peep|@prop:<id>>",
        help="Perform an authored quick action such as petting or searching a prop.",
    )
    registry.register(
        "activity_records",
        "Show personal and world records for an activity.",
        activity_hooks.activity_records_command,
        usage=".activity_records <kind>",
        toast=False,
        log=False,
        help="Reads the shared record table; only captured completed rounds count.",
    )
    registry.register(
        "activity_start",
        "Start a paid round for the open activity.",
        activity_hooks.activity_start_command,
        usage=".activity_start",
        toast=False,
        log=False,
        help="Charges the open activity's start cost for the new round.",
    )
    registry.register(
        "builder",
        "Grant builder power or list editable rooms.",
        privileged.builder_command,
        usage=".builder <grant|revoke|rooms> [@peep]",
        help="Admins grant or revoke the builder power; builders list rooms with owners and revisions.",
    )
    registry.register(
        "buy_pack",
        "Buy and open a card pack.",
        gameplay.buy_pack_command,
        usage=".buy_pack <pack_id> <operation_id>",
        help="Spend Bops to open a pack. The operation id makes purchases idempotent.",
    )
    registry.register("cancel", "Close the active activity window.", cancel_command, usage=".cancel")
    registry.register(
        "claim_bops",
        "Claim today's Daily Bops allowance.",
        gameplay.claim_bops_command,
        usage=".claim_bops",
    )
    registry.register(
        "craft",
        "Open the crafting activity for a crafting-station prop.",
        props.craft_command,
        usage=".craft @prop:<instance_id>",
        help="Open a crafting station bound to its recipes.",
    )
    registry.register(
        "craft_make",
        "Execute a craft with explicit ingredient stack selections.",
        props.craft_make_command,
        usage=".craft_make <recipe_id> <stack_id>:<quantity> ...",
    )
    registry.register(
        "craft_preview",
        "Preview a recipe and eligible ingredient stacks.",
        props.craft_preview_command,
        usage=".craft_preview <recipe_id>",
    )
    registry.register("dialog", "Choose a declarative dialog option.", dialog_command, usage=".dialog <index>")
    registry.register("dialog_end", "End the current conversation.", dialog_end_command, usage=".dialog_end")
    registry.register(
        "dispense",
        "Take a card from a dispenser prop.",
        props.dispense_command,
        usage=".dispense @prop:<instance_id>",
        help="Dispense a card from a prop's shared, recharging contents.",
    )
    registry.register(
        "drop",
        "Drop a quantity from one of your inventory stacks.",
        drop_command,
        usage=".drop @card:<stack_id> [quantity] [x y z]",
    )
    registry.register("emote", "Play an owned emote card.", gameplay.emote_command, usage=".emote @card:<stack_id>", toast=False)
    registry.register("equip", "Equip an item or action stack.", gameplay.equip_command, usage=".equip @card:<stack_id>")
    registry.register(
        "friend",
        "Manage friends and friend requests.",
        gameplay.friend_command,
        usage=".friend <add|accept|decline|cancel|remove> <peep>",
    )
    registry.register(
        "gm",
        "Game-master gameplay and state commands.",
        privileged.gm_command,
        usage=".gm <give|setcounter|buff|kudos|environment> ...",
        power="game-master",
        help="Grant cards, set counters, apply buffs, grant Kudos, or change room environment state.",
    )
    registry.register("go", "Move through an exit in the current room.", go_command, usage=".go @way:<exit_id>", toast=False)
    registry.register("help", "Show the available commands.", help_command, usage=".help", toast=False, log=False)
    registry.register("inspect", "Inspect a visible room entity.", inspect_command, usage=".inspect [target]", toast=False, log=False)
    registry.register("kick", "Disconnect a peep from the room.", privileged.kick_command, usage=".kick @peep [reason]", power="moderator")
    registry.register(
        "level_up",
        "Spend Kudos to reach the next level.",
        gameplay.level_up_command,
        usage=".level_up",
    )
    registry.register("look", "Look at the room or a visible entity.", look_command, usage=".look [target]", toast=False, log=False)
    registry.register(
        "memory_delete",
        "Delete one of your manual memories.",
        memory_delete_command,
        usage=".memory_delete @memory:<id>",
    )
    registry.register(
        "memory_edit",
        "Edit one of your manual memories.",
        memory_edit_command,
        usage=".memory_edit @memory:<id> <text>",
    )
    registry.register("memory_new", "Save the chat bar text as a memory.", memory_new_command, usage=".memory_new <text>")
    registry.register("memories", "List a month of journal memories.", memories_command, usage=".memories [year month]", toast=False, log=False)
    registry.register("merge", "Merge two stacks of the same card.", gameplay.merge_command, usage=".merge @card:<from> @card:<to> [quantity]")
    registry.register(
        "merge_all",
        "Merge every mergeable stack of each identical card.",
        gameplay.merge_all_command,
        usage=".merge_all",
        help="Consolidate duplicate inventory stacks up to each card's stack limit.",
    )
    registry.register("mute", "Mute a peep's chat.", privileged.mute_command, usage=".mute @peep <minutes>", power="moderator")
    registry.register("own", "Manage room ownership.", privileged.own_command, usage=".own <grant|remove|modify|show> <room_id> [@peep]", power="realtor")
    registry.register("packs", "List the card packs available for purchase.", gameplay.packs_command, usage=".packs")
    registry.register("pickup", "Pick up a room card stack quantity.", pickup_command, usage=".pickup @card:<stack_id> [quantity]")
    registry.register(
        "pin_peep",
        "Pin or unpin a peep in your sidebar.",
        gameplay.pin_peep_command,
        usage=".pin_peep <peep> [on|off]",
    )
    registry.register(
        "play",
        "Open a room activity or developer sample activity.",
        play_command,
        usage=".play <activity> [replace]",
    )
    registry.register(
        "reset_room",
        "Reset the current room's cards to the world definition.",
        reset_room_command,
        usage=".reset_room",
    )
    registry.register("say", "Send a room-scoped chat message.", say_command, usage=".say <text>", toast=False, log=False)
    registry.register(
        "sell",
        "Sell copies of an owned card stack for Bops.",
        gameplay.sell_command,
        usage=".sell @card:<stack_id> [quantity]",
        help="Sell collectible cards from your inventory at their rarity value.",
    )
    registry.register(
        "settings",
        "Change a persisted client setting.",
        settings_command,
        usage=".settings action-log <on|off>",
        toast=False,
        log=False,
    )
    registry.register("shop", "Open the card-pack shop.", gameplay.shop_command, usage=".shop")
    registry.register("skill", "Slot a skill card into an unlocked skill slot.", gameplay.skill_command, usage=".skill @card:<stack_id> <slot>")
    registry.register("split", "Split a stack into a new unequipped stack.", gameplay.split_command, usage=".split @card:<stack_id> <quantity>")
    registry.register("swap_sticker", "Swap your peep sticker for Bops.", gameplay.swap_sticker_command, usage=".swap_sticker <sticker>")
    registry.register("talk", "Talk to a peep and open its dialog.", talk_command, usage=".talk <peep>", toast=False, log=False)
    registry.register("task", "View one journal task.", task_command, usage=".task <task_id>", toast=False, log=False)
    registry.register("tasks", "List journal tasks.", tasks_command, usage=".tasks", toast=False, log=False)
    registry.register("unequip", "Unequip an item or action stack.", gameplay.unequip_command, usage=".unequip @card:<stack_id>")
    registry.register("unmute", "Remove a peep's mute.", privileged.unmute_command, usage=".unmute @peep", power="moderator")
    registry.register("unskill", "Remove a skill from a slot.", gameplay.unskill_command, usage=".unskill <slot>")
    registry.register("use", "Use an equipped item or action card.", gameplay.use_command, usage=".use @card:<stack_id> [target]")
    return registry


async def dispatch_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Dispatch a parsed normal command through the registry."""

    if command.kind == "admin":
        from server.commands.admin import dispatch_admin

        return await dispatch_admin(context, command)
    spec = context.registry.get(command.name)
    if spec is None:
        raise CommandError(f"Unknown command '.{command.name}'.")
    if spec.power is not None and not context.powers.has_power(context.account.id, spec.power):
        context.audit.safe_record(
            context.account.id,
            f"command.{spec.name}",
            None,
            "rejected",
            {"reason": "no_power", "power": spec.power},
        )
        raise CommandError(f"You do not have the {spec.power} power here.")
    outcome = await spec.handler(context, command)
    if isinstance(outcome, CommandOutcome):
        outcome.toast = spec.toast
        outcome.log = spec.log
    return outcome
