"""Milestone 2 gameplay command handlers."""

from __future__ import annotations

from dataclasses import replace

from server.behaviors.events import BehaviorEvent, PeepRef, PropRef
from server.commands.activity_launch import resolve_activity, start_activity
from server.commands.cutscenes import deliver, play_cutscene
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
    apply_behavior_inventory,
)
from server.commands.parser import ParsedCommand, parse_target
from server.commands.travel import departure_outcome, navigation_outcome
from server.profiles import AccountRecord
from server.services.actions import ActionResult, PropTarget

VALID_FRIEND_ACTIONS = {"add", "accept", "decline", "cancel", "remove", "list"}
MAX_PINNED_PEEPS = 25


def _require_card_target(command: ParsedCommand, index: int = 0) -> str:
    if len(command.args) <= index:
        raise ValueError("Choose a card.")
    token = command.args[index]
    if not token.startswith("@"):
        raise ValueError("Card targets must use @card:<id>.")
    target = parse_target(token)
    if target.kind != "card":
        raise ValueError("Card targets must use @card:<id>.")
    return target.value


async def _resolve_target(context: CommandContext, token: str | None) -> tuple[str | None, str, bool, str | None]:
    """Resolve a target token to (account_id, label, is_npc, peep_id)."""

    if token is None or token.lower() in {"self", "@self"}:
        return context.account.id, context.account.username_display, False, None
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    parsed = parse_target(token) if token.startswith("@") else None
    kind = parsed.kind if parsed else "username"
    value = parsed.value if parsed else token
    for occupant in await context.rooms.room_occupants(room_id):
        if kind == "peep" and occupant["id"] == value:
            return occupant["id"], str(occupant["username"]), False, None
        if kind == "username" and value.casefold() in {
            str(occupant["username"]).casefold(),
            str(occupant.get("label", "")).casefold(),
        }:
            return occupant["id"], str(occupant["username"]), False, None
    for peep in context.rooms.room_peeps(room_id):
        if kind == "peep" and peep["id"] == value:
            return None, str(peep["label"]), True, str(peep["id"])
        if kind == "username" and str(peep["label"]).casefold() == value.casefold():
            return None, str(peep["label"]), True, str(peep["id"])
    raise CommandError("That peep is not in this room.")


def _counter_events(context: CommandContext, result: ActionResult) -> list[PendingRoomBroadcast]:
    room_id = context.connection.room_id
    if room_id is None:
        return []
    broadcasts = []
    for effect in result.effects:
        event = {
            "type": "counter.updated",
            "room_id": room_id,
            "target_id": effect.target_account_id,
            "target_label": effect.target_label,
            "health_delta": effect.health_delta,
            "energy_delta": effect.energy_delta,
            "cleanliness_delta": effect.cleanliness_delta,
            "health": effect.health,
            "energy": effect.energy,
            "cleanliness": effect.cleanliness,
            "max_health": effect.max_health,
            "max_energy": effect.max_energy,
            "max_cleanliness": effect.max_cleanliness,
            "statuses": list(effect.statuses),
            "card_id": result.card_id,
            "source_id": context.account.id,
        }
        broadcasts.append(
            PendingRoomBroadcast(room_id=room_id, event=event)
        )
    return broadcasts


def _action_feedback(
    context: CommandContext, result: ActionResult, message: str | None = None
) -> list[dict[str, object]]:
    text = result.message if message is None else message
    events: list[dict[str, object]] = [
        {"type": "action.log", "text": text, "source": context.account.username_display}
    ]
    for effect in result.effects:
        if effect.health_delta or effect.energy_delta or effect.cleanliness_delta:
            events.append(
                {
                    "type": "toast",
                    "tone": "success",
                    "text": text,
                }
            )
            break
    return events


def _behavior_message(result: object | None) -> str | None:
    """Return the first non-empty message from a behavior result."""

    if result is None:
        return None
    for message in getattr(result, "messages", []):
        if message:
            return str(message)
    return None


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


def _resolve_account_target(context: CommandContext, token: str) -> AccountRecord:
    """Resolve a username or @peep target to an account."""

    parsed = parse_target(token) if token.startswith("@") else None
    account_id = parsed.value if parsed and parsed.kind == "peep" else None
    if account_id is not None:
        target = context.profiles.get_account_by_id(account_id)
    else:
        username = parsed.value if parsed else token
        target = context.profiles.get_account_by_username(username)
    if target is None:
        raise CommandError("That peep could not be found.")
    return target


def _resolve_prop_target(context: CommandContext, token: str) -> PropTarget:
    parsed = parse_target(token)
    if parsed.kind != "prop":
        raise CommandError("Prop targets must use @prop:<id>.")
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    prop = context.rooms.require_prop_target(room_id, parsed.value)
    return PropTarget(instance_id=prop.id, prop_id=prop.prop_id, room_id=room_id)


def _use_outcome(
    context: CommandContext, result: ActionResult, message: str | None = None
) -> CommandOutcome:
    outcome = CommandOutcome(
        message=result.message if message is None else message,
        payload={
            "inventory": context.cards.serialize_inventory_stacks(result.inventory),
            "user": _user_payload(context),
        },
        private_events=_action_feedback(context, result, message),
        room_broadcasts=_counter_events(context, result),
    )
    room_id = context.connection.room_id
    if result.room_event is not None and room_id is not None:
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=room_id, event=result.room_event)
        )
    return outcome


def _resolve_delegated_use(
    context: CommandContext,
    result: ActionResult,
    behavior: object | None,
    stack_id: str,
) -> ActionResult:
    """Commit a delegated card use only when a behavior actually acted."""

    if not result.delegated:
        return result
    if behavior is not None and getattr(behavior, "acted", False):
        return context.actions.commit_delegated_use(context.account, stack_id=stack_id)
    return replace(result, message="Nothing happens.", cutscene=None)


async def use_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    target_token = command.args[1] if len(command.args) > 1 else None
    if target_token is not None and target_token.startswith("@prop:"):
        room_id = context.connection.room_id
        if room_id is None:
            raise CommandError("You are not currently in a room.")
        prop_target = _resolve_prop_target(context, target_token)
        prop_definition = context.world.props.get(prop_target.prop_id)
        if prop_definition is not None and prop_definition.behavior == "container":
            # Storing a card in a container is not "using" it: no Energy is
            # charged and one-use cards are kept intact inside the container.
            try:
                deposit = context.containers.deposit(
                    context.account, room_id, prop_target.instance_id, stack_id
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            return CommandOutcome(
                message=f"Stored {deposit.label}.",
                payload={
                    "inventory": context.cards.serialize_inventory_stacks(deposit.stacks),
                    "user": _user_payload(context),
                    "container": context.containers.contents(room_id, prop_target.instance_id),
                },
                private_events=[
                    {"type": "toast", "tone": "success", "text": f"Stored {deposit.label}."}
                ],
            )
        result = context.actions.use_card(
            context.account,
            stack_id=stack_id,
            target_prop=prop_target,
            room_id=room_id,
        )
        behavior = None
        if result.delegated:
            behavior = await context.behaviors.dispatch(
                BehaviorEvent(
                    type="card_play",
                    actor=PeepRef(kind="user", peep_id=None, account_id=context.account.id),
                    target=PropRef(
                        instance_id=prop_target.instance_id,
                        prop_id=prop_target.prop_id,
                        room_id=prop_target.room_id,
                    ),
                    room_id=room_id,
                    action="use",
                    data={"card_id": result.card_id, "stack_id": stack_id},
                )
            )
        result = _resolve_delegated_use(context, result, behavior, stack_id)
        outcome = _use_outcome(context, result, _behavior_message(behavior))
        if behavior is not None:
            outcome.private_events.extend(getattr(behavior, "private_events", []))
            outcome.room_broadcasts.extend(getattr(behavior, "room_broadcasts", []))
            apply_behavior_inventory(context, outcome, behavior)
        if result.cutscene:
            launch = await play_cutscene(
                context,
                reference=result.cutscene,
                room_id=room_id,
                origin="card",
                target=f"@prop:{prop_target.instance_id}",
                params={"card": f"$card:{result.card_id}"},
            )
            private_events, room_broadcasts = deliver(launch)
            outcome.private_events.extend(private_events)
            outcome.room_broadcasts.extend(room_broadcasts)
        return outcome

    target_id, target_label, target_is_npc, target_peep_id = await _resolve_target(context, target_token)
    result = context.actions.use_card(
        context.account,
        stack_id=stack_id,
        target_account_id=target_id,
        target_label=target_label,
        target_is_npc=target_is_npc,
        room_id=context.connection.room_id,
    )
    behavior = None
    if target_token is not None:
        room_id = context.connection.room_id
        target_ref = (
            PeepRef(kind="npc", peep_id=target_peep_id, account_id=None)
            if target_is_npc
            else PeepRef(kind="user", peep_id=None, account_id=target_id)
        )
        behavior = await context.behaviors.dispatch(
            BehaviorEvent(
                type="card_play",
                actor=PeepRef(kind="user", peep_id=None, account_id=context.account.id),
                target=target_ref,
                room_id=room_id,
                action="use",
                data={"card_id": result.card_id, "stack_id": stack_id, "target_label": target_label},
            )
        )
        result = _resolve_delegated_use(context, result, behavior, stack_id)
    outcome = _use_outcome(context, result, _behavior_message(behavior))
    if behavior is not None:
        outcome.private_events.extend(getattr(behavior, "private_events", []))
        outcome.room_broadcasts.extend(getattr(behavior, "room_broadcasts", []))
        apply_behavior_inventory(context, outcome, behavior)
    return outcome


async def play_cutscene_emote(context: CommandContext, result: ActionResult) -> CommandOutcome:
    """Broadcast the cutscene a cutscene emote card points at."""

    if context.connection.room_id is None:
        raise CommandError("You are not currently in a room.")
    launch = await play_cutscene(
        context,
        reference=str(result.cutscene),
        room_id=context.connection.room_id,
        origin="emote",
        params={"card": result.card_id},
    )
    private_events, room_broadcasts = deliver(launch)
    return CommandOutcome(
        message=result.message,
        payload={
            "inventory": context.cards.serialize_inventory_stacks(result.inventory),
            "user": _user_payload(context),
        },
        private_events=[
            *private_events,
            {"type": "action.log", "text": result.message, "source": context.account.username_display},
        ],
        room_broadcasts=room_broadcasts,
    )


async def emote_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    result = context.actions.use_emote(context.account, stack_id=stack_id)
    room_id = context.connection.room_id
    if result.cutscene:
        return await play_cutscene_emote(context, result)
    broadcasts = []
    if room_id is not None and result.bubble is not None:
        event = {
            "type": "emote.bubble",
            "room_id": room_id,
            "source_id": context.account.id,
            "source": context.account.username_display,
            "bubble": result.bubble,
            "card_id": result.card_id,
        }
        broadcasts.append(
            PendingRoomBroadcast(room_id=room_id, event=event)
        )
    return CommandOutcome(
        message=result.message,
        payload={
            "inventory": context.cards.serialize_inventory_stacks(result.inventory),
            "user": _user_payload(context),
        },
        private_events=[{"type": "action.log", "text": result.message, "source": context.account.username_display}],
        room_broadcasts=broadcasts,
    )


async def equip_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    mutation = context.inventory.equip(context.account, stack_id)
    return CommandOutcome(
        message="Card equipped.",
        payload={
            "inventory": context.cards.serialize_inventory_stacks(mutation.stacks),
            "user": _user_payload(context),
        },
    )


async def unequip_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    mutation = context.inventory.unequip(context.account, stack_id)
    return CommandOutcome(
        message="Card unequipped.",
        payload={
            "inventory": context.cards.serialize_inventory_stacks(mutation.stacks),
            "user": _user_payload(context),
        },
    )


async def split_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    if len(command.args) < 2:
        raise CommandError("Choose how many copies to split off.")
    try:
        quantity = int(command.args[1])
    except ValueError as exc:
        raise CommandError("Split quantity must be an integer.") from exc
    mutation = context.inventory.split(context.account, stack_id, quantity)
    return CommandOutcome(
        message="Stack split.",
        payload={
            "inventory": context.cards.serialize_inventory_stacks(mutation.stacks),
            "user": _user_payload(context),
        },
    )


async def merge_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    source_id = _require_card_target(command, 0)
    destination_id = _require_card_target(command, 1)
    quantity = None
    if len(command.args) > 2:
        try:
            quantity = int(command.args[2])
        except ValueError as exc:
            raise CommandError("Merge quantity must be an integer.") from exc
    mutation = context.inventory.merge(context.account, source_id, destination_id, quantity)
    return CommandOutcome(
        message="Stacks merged.",
        payload={
            "inventory": context.cards.serialize_inventory_stacks(mutation.stacks),
            "user": _user_payload(context),
        },
    )


async def merge_all_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    mutation = context.inventory.auto_merge(context.account)
    return CommandOutcome(
        message="Stacks merged.",
        payload={
            "inventory": context.cards.serialize_inventory_stacks(mutation.stacks),
            "user": _user_payload(context),
        },
    )


async def sell_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    quantity = 1
    if len(command.args) > 1:
        try:
            quantity = int(command.args[1])
        except ValueError as exc:
            raise CommandError("Sell quantity must be an integer.") from exc
    result = context.pricing.sell(context.account, stack_id, quantity)
    return CommandOutcome(
        message=f"Sold {result.quantity}× {result.definition.label} for {result.bops_gained} Bops.",
        payload={
            "sale": {
                "card_id": result.definition.id,
                "quantity": result.quantity,
                "bops_gained": result.bops_gained,
            },
            "inventory": context.cards.serialize_inventory_stacks(result.stacks),
            "user": _user_payload(context),
        },
        private_events=[{"type": "toast", "tone": "success", "text": f"+{result.bops_gained} Bops", "silent": True}],
    )


async def skill_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    if len(command.args) < 2:
        raise CommandError("Choose a skill slot index.")
    try:
        slot_index = int(command.args[1])
    except ValueError as exc:
        raise CommandError("Skill slot index must be an integer.") from exc
    snapshot = context.progression.slot_skill(context.account, slot_index, stack_id)
    return CommandOutcome(message="Skill slotted.", payload={"user": _user_payload(context), "counters": snapshot.payload()})


async def unskill_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a skill slot index to clear.")
    try:
        slot_index = int(command.args[0])
    except ValueError as exc:
        raise CommandError("Skill slot index must be an integer.") from exc
    snapshot = context.progression.remove_skill(context.account, slot_index)
    return CommandOutcome(message="Skill removed.", payload={"user": _user_payload(context), "counters": snapshot.payload()})


async def level_up_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    result = context.progression.level_up(context.account)
    _, newly = context.titles.sync_unlocked(result.account.id)
    private_events = [{"type": "toast", "tone": "success", "text": f"Level up! Welcome, {context.content.levels.get(result.account.level).label}."}]
    for part in newly:
        private_events.append({"type": "toast", "tone": "success", "text": f"Title unlocked: {part['label']}."})
    return CommandOutcome(
        message=f"You reached level {result.account.level}!",
        payload={"user": _user_payload(context), "counters": result.snapshot.payload()},
        private_events=private_events,
    )


async def claim_bops_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    amount, _account = context.progression.claim_daily_bops(context.account)
    return CommandOutcome(
        message=f"Claimed {amount} Daily Bops.",
        payload={"user": _user_payload(context)},
        private_events=[{"type": "toast", "tone": "success", "text": f"+{amount} Bops"}],
    )


async def buy_pack_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 2:
        raise CommandError("Use '.buy_pack <pack> <operation_id>'.")
    token = command.args[0]
    pack_id = parse_target(token).value if token.startswith("@") else token
    operation_id = command.args[1]
    result = context.shop.purchase(context.account, pack_id, operation_id)
    return CommandOutcome(
        message=f"Purchased {result.pack.label}.",
        payload={
            "purchase": {
                "pack_id": result.pack.id,
                "pack_card": context.cards.serialize_definition(result.pack_card),
                "replayed": result.replayed,
                "bops_spent": result.bops_spent,
            },
            "inventory": context.cards.serialize_inventory_stacks(result.stacks),
            "user": _user_payload(context),
        },
    )


async def open_pack_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 2:
        raise CommandError("Use '.open_pack <pack> <operation_id>'.")
    stack_id = _require_card_target(command, 0)
    operation_id = command.args[1]
    result = context.shop.open_pack(context.account, stack_id, operation_id)
    private_events: list[dict[str, object]] = []
    if not result.replayed and context.connection.room_id is not None:
        sealed = context.shop.sealed_definition(result.pack.id)
        params: dict[str, object] = {"pack_label": result.pack.label}
        if sealed is not None:
            params["pack_art"] = f"$card:{sealed.id}"
        for index, card in enumerate(result.cards, start=1):
            params[f"card{index}"] = f"$card:{card.id}"
            params[f"rarity{index}"] = card.rarity or "Common"
        try:
            launch = await play_cutscene(
                context,
                reference="pack-open",
                room_id=context.connection.room_id,
                audience="private",
                origin="pack",
                params=params,
            )
        except CommandError:
            launch = None
        if launch is not None:
            private_events, _ = deliver(launch)
    return CommandOutcome(
        message=f"Opened {result.pack.label}.",
        payload={
            "opened": {
                "pack_id": result.pack.id,
                "cards": [context.cards.serialize_definition(card) for card in result.cards],
                "replayed": result.replayed,
            },
            "inventory": context.cards.serialize_inventory_stacks(result.stacks),
            "user": _user_payload(context),
        },
        private_events=private_events,
    )


async def shop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    section = command.args[0].lower() if command.args else "cards"
    if section not in {"cards", "props"}:
        section = "cards"
    resolved = resolve_activity(context, room_id, "shop")
    return start_activity(
        context,
        resolved,
        room_id=room_id,
        replace_existing=True,
        extra_config={"section": section},
    )


async def friend_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Use '.friend <add|accept|decline|cancel|remove|list> [peep]'.")
    action = command.args[0].lower()
    if action not in VALID_FRIEND_ACTIONS:
        raise CommandError("Unknown friend action.")
    if action == "list":
        return CommandOutcome(payload={"user": _user_payload(context)}, toast=False, log=False)
    if len(command.args) < 2:
        raise CommandError("Choose a peep.")
    target = _resolve_account_target(context, command.args[1])
    if action == "add":
        context.friends.send_request(context.account, target)
        message = f"Friend request sent to {target.username_display}."
    elif action == "accept":
        context.friends.accept_request(context.account, target.id)
        message = f"You are now friends with {target.username_display}."
    elif action == "decline":
        context.friends.decline_request(context.account, target.id)
        message = "Friend request declined."
    elif action == "cancel":
        context.friends.cancel_request(context.account, target.id)
        message = "Friend request cancelled."
    else:
        context.friends.remove_friend(context.account, target.id)
        message = f"Removed {target.username_display} from your friends."
    return CommandOutcome(message=message, payload={"user": _user_payload(context)})


async def _visit_npc(
    context: CommandContext,
    world_id: str,
    npc_id: str,
    source_room_id: str,
) -> CommandOutcome:
    """Move the caller to an NPC's current room in this world."""

    if not npc_id:
        raise CommandError("Choose a peep to visit.")
    if world_id != context.world.id:
        raise CommandError("That peep is not in this world.")
    peep = context.world.peeps.get(npc_id)
    if peep is None:
        raise CommandError("That peep could not be found.")
    destination_room_id = context.rooms.peep_room(peep)
    if destination_room_id == source_room_id:
        return CommandOutcome(message=f"{peep.label} is already here.")
    navigation = await context.rooms.enter_room(
        context.account,
        source_room_id,
        destination_room_id,
        direction=f"visiting {peep.label}",
    )
    return navigation_outcome(
        context,
        navigation,
        message=f"You visit {peep.label}.",
    )


async def _visit_friend(
    context: CommandContext,
    target: AccountRecord,
    source_room_id: str,
) -> CommandOutcome:
    """Move the caller to a friend's current room, across worlds when allowed."""

    if target.id == context.account.id:
        raise CommandError("You cannot visit yourself.")
    actor_profile = context.profiles.get_user_profile(context.account.id)
    if actor_profile is None or target.id not in actor_profile.friends:
        raise CommandError("You can only visit friends.")
    profile = context.profiles.get_user_profile(target.id)
    if profile is None:
        raise CommandError("That peep could not be found.")
    local = await context.connections.get(target.id)
    if local is not None:
        room_id = local.room_id or profile.remembered_room or context.world.entry_room_id
        if room_id not in context.world.rooms:
            room_id = context.world.entry_room_id
        if room_id == source_room_id:
            return CommandOutcome(message=f"You are already with {target.username_display}.")
        navigation = await context.rooms.enter_room(
            context.account,
            source_room_id,
            room_id,
            direction=f"visiting {target.username_display}",
        )
        return navigation_outcome(
            context,
            navigation,
            message=f"You visit {target.username_display}.",
        )
    if profile.last_world_id == context.world.id or not profile.last_world_id:
        raise CommandError(f"{target.username_display} is not online.")
    context.cross_world.check_multiverse_access(context.account)
    worlds = await context.cross_world.list_worlds()
    online = any(
        isinstance(world.get("online_account_ids"), list)
        and target.id in {str(entry) for entry in world.get("online_account_ids") or []}
        for world in worlds
    )
    if not online:
        raise CommandError(f"{target.username_display} is not online.")
    plan = await context.cross_world.prepare_world(
        context.account,
        profile.last_world_id,
        profile.remembered_room or None,
    )
    departure = await context.rooms.depart_to_world(
        context.account,
        source_room_id,
        direction=f"visiting {target.username_display}",
        destination_room_id=plan.room_id or None,
    )
    payload = context.cross_world.commit(
        context.account,
        plan,
        source_room_id=source_room_id,
        source_room_label=context.rooms.room_definition(source_room_id).label,
        source_world_label=context.world.label,
    )
    return departure_outcome(
        context,
        departure,
        payload,
        message=f"You travel across worlds to {target.username_display}.",
    )


async def goto_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Visit a friend or peep at their current position."""

    if not command.args:
        raise CommandError("Choose a friend or peep to visit.")
    token = command.args[0]
    source_room_id = context.connection.room_id
    if source_room_id is None:
        raise CommandError("You are not currently in a room.")
    if token.startswith("@npc:"):
        world_id, separator, npc_id = token[len("@npc:"):].partition(":")
        if separator:
            return await _visit_npc(context, world_id.strip(), npc_id.strip(), source_room_id)
        return await _visit_npc(context, context.world.id, world_id.strip(), source_room_id)
    if token.startswith("@peep:"):
        account_id = token[len("@peep:"):].strip()
        if not account_id:
            raise CommandError("Choose a friend or peep to visit.")
        target = context.profiles.get_account_by_id(account_id)
        if target is not None:
            return await _visit_friend(context, target, source_room_id)
        return await _visit_npc(context, context.world.id, account_id, source_room_id)
    raise CommandError("Choose a friend or peep to visit.")


async def pin_peep_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a peep to pin or unpin.")
    token = command.args[0]
    parsed = parse_target(token) if token.startswith("@") else None
    if parsed is not None and parsed.kind == "peep":
        if context.profiles.get_account_by_id(parsed.value) is None:
            raise CommandError("That peep could not be found.")
    peep_id = parsed.value if parsed else token
    mode = command.args[1].lower() if len(command.args) > 1 else "toggle"
    if mode not in {"toggle", "on", "off"}:
        raise CommandError("Pin mode must be on, off, or omitted.")

    def mutate(data: dict[str, object]) -> None:
        raw = data.get("pinned_peeps")
        pinned = list(raw) if isinstance(raw, list) else []
        if mode == "on":
            if peep_id not in pinned:
                pinned.append(peep_id)
        elif mode == "off":
            pinned = [entry for entry in pinned if entry != peep_id]
        elif peep_id in pinned:
            pinned.remove(peep_id)
        else:
            pinned.append(peep_id)
        if len(pinned) > MAX_PINNED_PEEPS:
            raise ValueError(f"You can pin at most {MAX_PINNED_PEEPS} peeps.")
        data["pinned_peeps"] = pinned

    profile = context.profiles.update_profile(context.account.id, mutate)
    return CommandOutcome(
        message="Pins updated.",
        payload={"pinned_peeps": list(profile.pinned_peeps), "user": _user_payload(context)},
    )


async def swap_sticker_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if not command.args:
        raise CommandError("Choose a sticker to swap to.")
    token = command.args[0]
    sticker = parse_target(token).value if token.startswith("@") else token
    account = context.shop.swap_sticker(context.account, sticker, context.valid_stickers)
    return CommandOutcome(
        message="Sticker updated.",
        payload={"user": context.serialize_user(account)},
    )


async def sprite_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Move the acting user's sprite on a sprite-mode room board."""

    if len(command.args) < 3 or command.args[0].lower() != "move":
        raise CommandError("Use '.sprite move <x> <y>'.")
    try:
        x = float(command.args[1])
        y = float(command.args[2])
    except ValueError as exc:
        raise CommandError("Sprite coordinates must be numbers.") from exc
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    event = context.rooms.move_user_sprite(context.account, room_id, x, y)
    return CommandOutcome(
        room_broadcasts=[PendingRoomBroadcast(room_id=room_id, event=event)],
        toast=False,
        log=False,
    )


async def packs_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    return CommandOutcome(
        message="Pack list loaded.",
        payload={"packs": [preview.as_dict() for preview in context.shop.packs()]},
    )
