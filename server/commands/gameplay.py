"""Milestone 2 gameplay command handlers."""

from __future__ import annotations

from server.behaviors.events import BehaviorEvent, PeepRef
from server.commands.activity_launch import resolve_activity, start_activity
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome, PendingRoomBroadcast
from server.commands.parser import ParsedCommand, parse_target
from server.services.actions import ActionResult

VALID_FRIEND_ACTIONS = {"add", "accept", "decline", "cancel", "remove"}
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
        if kind == "username" and str(occupant["username"]).casefold() == value.casefold():
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
            "health": effect.health,
            "energy": effect.energy,
            "max_health": effect.max_health,
            "max_energy": effect.max_energy,
            "statuses": list(effect.statuses),
            "card_id": result.card_id,
            "source_id": context.account.id,
        }
        broadcasts.append(
            PendingRoomBroadcast(room_id=room_id, event=event)
        )
    return broadcasts


def _action_feedback(context: CommandContext, result: ActionResult) -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {"type": "action.log", "text": result.message, "source": context.account.username_display}
    ]
    for effect in result.effects:
        if effect.health_delta or effect.energy_delta:
            events.append(
                {
                    "type": "toast",
                    "tone": "success",
                    "text": result.message,
                }
            )
            break
    return events


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


async def use_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    target_token = command.args[1] if len(command.args) > 1 else None
    target_id, target_label, target_is_npc, target_peep_id = await _resolve_target(context, target_token)
    result = context.actions.use_card(
        context.account,
        stack_id=stack_id,
        target_account_id=target_id,
        target_label=target_label,
        target_is_npc=target_is_npc,
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
    outcome = CommandOutcome(
        message=result.message,
        payload={
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in result.inventory],
            "user": _user_payload(context),
        },
        private_events=_action_feedback(context, result),
        room_broadcasts=_counter_events(context, result),
    )
    if behavior is not None:
        outcome.private_events.extend(getattr(behavior, "private_events", []))
        outcome.room_broadcasts.extend(getattr(behavior, "room_broadcasts", []))
    return outcome


async def emote_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    result = context.actions.use_emote(context.account, stack_id=stack_id)
    room_id = context.connection.room_id
    broadcasts = []
    if room_id is not None and result.room_effect is not None:
        event = {
            "type": "effect.queued",
            "room_id": room_id,
            "effect": result.room_effect,
            "card_id": result.card_id,
            "source_id": context.account.id,
            "source": context.account.username_display,
        }
        broadcasts.append(
            PendingRoomBroadcast(room_id=room_id, event=event)
        )
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
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in result.inventory],
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
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in mutation.stacks],
            "user": _user_payload(context),
        },
    )


async def unequip_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    stack_id = _require_card_target(command)
    mutation = context.inventory.unequip(context.account, stack_id)
    return CommandOutcome(
        message="Card unequipped.",
        payload={
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in mutation.stacks],
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
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in mutation.stacks],
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
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in mutation.stacks],
            "user": _user_payload(context),
        },
    )


async def merge_all_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    mutation = context.inventory.auto_merge(context.account)
    return CommandOutcome(
        message="Stacks merged.",
        payload={
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in mutation.stacks],
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
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in result.stacks],
            "user": _user_payload(context),
        },
        private_events=[{"type": "toast", "tone": "success", "text": f"+{result.bops_gained} Bops"}],
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
    return CommandOutcome(
        message=f"You reached level {result.account.level}!",
        payload={"user": _user_payload(context), "counters": result.snapshot.payload()},
        private_events=[{"type": "toast", "tone": "success", "text": f"Level up! Welcome, {context.content.levels.get(result.account.level).label}."}],
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
        message=f"Opened {result.pack.label}.",
        payload={
            "purchase": {
                "pack_id": result.pack.id,
                "cards": [context.cards.serialize_definition(card) for card in result.cards],
                "replayed": result.replayed,
                "bops_spent": result.bops_spent,
            },
            "inventory": [context.cards.serialize_inventory_stack(stack) for stack in result.stacks],
            "user": _user_payload(context),
        },
        private_events=[
            {"type": "shop.reveal", "pack_id": result.pack.id, "cards": [card.id for card in result.cards]}
        ],
    )


async def shop_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    resolved = resolve_activity(context, room_id, "shop")
    return start_activity(context, resolved, room_id=room_id, replace_existing=False)


async def friend_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    if len(command.args) < 2:
        raise CommandError("Use '.friend <add|accept|decline|cancel|remove> <peep>'.")
    action = command.args[0].lower()
    if action not in VALID_FRIEND_ACTIONS:
        raise CommandError("Unknown friend action.")
    token = command.args[1]
    parsed = parse_target(token) if token.startswith("@") else None
    account_id = parsed.value if parsed and parsed.kind == "peep" else None
    target = None
    if account_id is not None:
        target = context.profiles.get_account_by_id(account_id)
    else:
        username = parsed.value if parsed else token
        target = context.profiles.get_account_by_username(username)
    if target is None:
        raise CommandError("That peep could not be found.")
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


async def packs_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    del command
    return CommandOutcome(
        message="Pack list loaded.",
        payload={"packs": [preview.as_dict() for preview in context.shop.packs()]},
    )
