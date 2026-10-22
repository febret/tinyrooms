"""TinyTown mod core."""

from __future__ import annotations

from mods.tinytown.catalog import DISTRICTS_BY_ID
from mods.tinytown.service import TinytownService
from server.commands.activity_launch import ResolvedActivity, start_activity
from server.commands.core import require_room_id
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
    merge_behavior_result,
)
from server.commands.parser import ParsedCommand


MOD_ID = "tinytown"
_LOCK_ON = frozenset({"on", "true", "yes", "lock", "locked"})
_LOCK_OFF = frozenset({"off", "false", "no", "unlock", "unlocked"})


def _service(context: CommandContext) -> TinytownService:
    service = context.mods.get(MOD_ID)
    if not isinstance(service, TinytownService) or not service.available:
        raise CommandError("TinyTown is not available here.")
    return service


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


def _toast(outcome: CommandOutcome, text: str, tone: str = "success") -> CommandOutcome:
    outcome.private_events.append({"type": "toast", "tone": tone, "text": text})
    return outcome


def _owned_current_room(context: CommandContext, service: TinytownService) -> tuple[str, object]:
    room_id = require_room_id(context)
    house = service.housing.require_owned_room(context.account, room_id)
    return room_id, house


def _speak(context: CommandContext, npc_id: str, name: str, text: str, room_id: str) -> PendingRoomBroadcast:
    context.world_state.append_chat_message(
        room_id,
        {
            "speaker_id": npc_id,
            "speaker": name,
            "style": "expression",
            "text": text,
        },
    )
    return PendingRoomBroadcast(
        room_id=room_id,
        event={
            "type": "emote.bubble",
            "room_id": room_id,
            "source_id": npc_id,
            "speaker_id": npc_id,
            "source": name,
            "bubble": {"kind": "expression", "text": text},
            "card_id": None,
        },
    )


async def _open_activity(
    context: CommandContext,
    kind: str,
    *,
    room_id: str | None,
    replace_existing: bool,
) -> CommandOutcome:
    definition = context.world.activities.get(kind)
    if definition is None:
        raise CommandError("That TinyTown activity is unavailable.")
    resolved = ResolvedActivity(definition=definition, room_bound=room_id is not None)
    return start_activity(
        context,
        resolved,
        room_id=room_id or require_room_id(context),
        replace_existing=replace_existing,
    )


async def tinytown_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open TinyTown or manage homes, household peeps, and decorations."""

    service = _service(context)
    if not command.args:
        return await _open_activity(context, "tinytown", room_id=None, replace_existing=True)
    action = command.args[0].lower()
    housing = service.housing

    if action in {"open", "home"}:
        return await _open_activity(context, "tinytown", room_id=None, replace_existing=True)

    if action == "list":
        account = context.profiles.get_account_by_id(context.account.id) or context.account
        welcome = housing.ensure_welcome_grant(account)
        if welcome:
            outcome = CommandOutcome(
                payload={},
                toast=False,
                log=False,
            )
            outcome.private_events.append(
                {
                    "type": "toast",
                    "tone": "success",
                    "text": f"TinyTown welcome grant: {welcome} Bops. Enough for a first front door.",
                }
            )
            account = context.profiles.get_account_by_id(context.account.id) or account
        else:
            outcome = None
        payload = housing.list_payload(account)
        room_id = context.connection.room_id
        current_house = housing.current_house(room_id) if room_id else None
        payload.update(
            {
                "current_room_id": room_id or "",
                "current_house_id": current_house.house_id if current_house else "",
                "current_is_owned": bool(
                    current_house is not None and current_house.owner_account_id == context.account.id
                ),
                "user": context.serialize_user(account),
            }
        )
        result = outcome or CommandOutcome(toast=False, log=False)
        result.payload = payload
        return result

    if action == "buy":
        if len(command.args) < 2:
            raise CommandError("Use '.tinytown buy <template_id>'.")
        record = housing.purchase(context.account, command.args[1])
        house = housing.house_payload(record, context.account.id)
        return _toast(
            CommandOutcome(
                message=f"You bought the {house['label']}.",
                payload={"house": house, "user": _user_payload(context)},
                toast=False,
            ),
            f"The keys to the {house['label']} are yours.",
        )

    if action in {"enter", "visit"}:
        house_id = command.args[1] if len(command.args) > 1 else None
        if house_id is None:
            owned = housing.records_for_owner(context.account.id)
            if not owned:
                raise CommandError("You do not own a home yet.")
            house_id = owned[0].house_id
        record = housing.require_entry(context.account, house_id)
        room_id = housing.entry_room(record)
        source_room = require_room_id(context)
        if source_room == room_id:
            raise CommandError("You are already there.")
        navigation = await context.rooms.enter_room(
            context.account,
            source_room,
            room_id,
            direction="a front door",
        )
        house = housing.house_payload(record, context.account.id)
        outcome = CommandOutcome(
            message=f"You step into {house['owner_username']}'s {house['label']}.",
            payload={"room_id": navigation.destination_room_id, "house": house},
            snapshot=navigation.destination_snapshot,
            toast=False,
        )
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.source_room_id, event=navigation.source_event)
        )
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.destination_room_id, event=navigation.destination_event)
        )
        if navigation.closed_activity is not None:
            outcome.private_events.append(
                {
                    "type": "activity.closed",
                    "activity": navigation.closed_activity,
                    "reason": "room_changed",
                }
            )
        for behavior in navigation.behavior_results:
            merge_behavior_result(context, outcome, behavior)
        return outcome

    if action == "lock":
        if len(command.args) < 3:
            raise CommandError("Use '.tinytown lock <house_id> <on|off>'.")
        value = command.args[2].lower()
        if value in _LOCK_ON:
            locked = True
        elif value in _LOCK_OFF:
            locked = False
        else:
            raise CommandError("Lock must be on or off.")
        record = housing.set_locked(context.account, command.args[1], locked)
        house = housing.house_payload(record, context.account.id)
        return _toast(
            CommandOutcome(
                message="Your front door is locked." if locked else "Your front door is unlocked.",
                payload={"house": house},
                toast=False,
            ),
            "Front door locked." if locked else "Front door unlocked.",
        )

    if action == "household":
        house_id = command.args[1] if len(command.args) > 1 else None
        payload = service.npcs.household_payload(context.account, house_id)
        payload["user"] = _user_payload(context)
        return CommandOutcome(payload=payload, toast=False, log=False)

    if action == "npc":
        if len(command.args) < 2:
            payload = service.npcs.household_payload(context.account)
            payload["user"] = _user_payload(context)
            return CommandOutcome(payload=payload, toast=False, log=False)
        sub = command.args[1].lower()
        if sub == "add":
            if len(command.args) < 7:
                raise CommandError(
                    "Use '.tinytown npc add <house_id> <name> <avatar> <trait> <trait>'."
                )
            record = service.npcs.add(
                context.account,
                command.args[2],
                command.args[3],
                command.args[4],
                [command.args[5], command.args[6]],
            )
            payload = service.npcs.household_payload(context.account, record.house_id)
            payload["user"] = _user_payload(context)
            outcome = CommandOutcome(
                message=f"{record.name} moved in.",
                payload=payload,
                toast=False,
            )
            if context.connection.room_id == record.room_id:
                outcome.room_broadcasts.append(
                    PendingRoomBroadcast(
                        room_id=record.room_id,
                        event={"type": "room.refresh", "room_id": record.room_id},
                    )
                )
                outcome.snapshot = await context.rooms.build_snapshot(context.account, record.room_id)
            return _toast(outcome, f"{record.name} has moved in.")
        if sub == "edit":
            if len(command.args) < 7:
                raise CommandError(
                    "Use '.tinytown npc edit <npc_id> <name> <avatar> <trait> <trait>'."
                )
            record = service.npcs.edit(
                context.account,
                command.args[2],
                name=command.args[3],
                avatar=command.args[4],
                traits=[command.args[5], command.args[6]],
            )
            payload = service.npcs.household_payload(context.account, record.house_id)
            payload["user"] = _user_payload(context)
            outcome = CommandOutcome(message=f"{record.name} updated.", payload=payload, toast=False)
            if context.connection.room_id == record.room_id:
                outcome.room_broadcasts.append(
                    PendingRoomBroadcast(
                        room_id=record.room_id,
                        event={"type": "room.refresh", "room_id": record.room_id},
                    )
                )
                outcome.snapshot = await context.rooms.build_snapshot(context.account, record.room_id)
            return _toast(outcome, f"{record.name} updated.")
        if sub == "remove":
            if len(command.args) < 3:
                raise CommandError("Use '.tinytown npc remove <npc_id>'.")
            record = service.npcs.remove(context.account, command.args[2])
            payload = service.npcs.household_payload(context.account, record.house_id)
            payload["user"] = _user_payload(context)
            outcome = CommandOutcome(message=f"{record.name} moved out.", payload=payload, toast=False)
            if context.connection.room_id == record.room_id:
                outcome.room_broadcasts.append(
                    PendingRoomBroadcast(
                        room_id=record.room_id,
                        event={"type": "room.refresh", "room_id": record.room_id},
                    )
                )
                outcome.snapshot = await context.rooms.build_snapshot(context.account, record.room_id)
            return _toast(outcome, f"{record.name} moved out.")

        room_id = require_room_id(context)
        record, summary, line = service.npcs.checkin(context.account, command.args[1], room_id)
        outcome = CommandOutcome(message=summary, payload={"npc": service.npcs.npc_summary(record, "here")}, toast=False)
        outcome.room_broadcasts.append(_speak(context, record.npc_id, record.name, line, room_id))
        return _toast(outcome, summary)

    if action == "play":
        if len(command.args) < 2:
            raise CommandError("Use '.tinytown play <npc_id>'.")
        room_id = require_room_id(context)
        record, line, stats = service.npcs.play(context.account, command.args[1], room_id)
        outcome = CommandOutcome(message=line, payload={"npc_name": record.name}, toast=False)
        outcome.room_broadcasts.append(_speak(context, record.npc_id, record.name, line, room_id))
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=room_id,
                event={
                    "type": "counter.updated",
                    "room_id": room_id,
                    "target_id": record.npc_id,
                    "target_label": record.name,
                    "health": stats.get("health", 0),
                    "energy": stats.get("energy", 0),
                    "cleanliness": stats.get("cleanliness", 0),
                    "max_health": 100,
                    "max_energy": 100,
                    "max_cleanliness": 100,
                    "statuses": [],
                    "decals": [],
                    "source_id": context.account.id,
                },
            )
        )
        return _toast(outcome, line)

    if action == "decor":
        room_id = require_room_id(context)
        payload = service.housing.decor_payload(context.account, room_id)
        payload["user"] = _user_payload(context)
        return CommandOutcome(payload=payload, toast=False, log=False)

    if action == "artstore":
        room_id = require_room_id(context)
        service.housing.require_owned_room(context.account, room_id)
        return await _open_activity(context, "art-store", room_id=room_id, replace_existing=True)

    if action == "floor":
        if len(command.args) < 2:
            raise CommandError("Use '.tinytown floor <floor_id>'.")
        room_id, _house = _owned_current_room(context, service)
        result = service.housing.buy_floor(context.account, room_id, command.args[1])
        outcome = CommandOutcome(
            message=result.message,
            payload={"user": _user_payload(context), "decoration": {"bops_spent": result.bops_spent}},
            toast=False,
        )
        outcome.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=result.layout_event))
        if room_id == context.connection.room_id:
            outcome.snapshot = await context.rooms.build_snapshot(context.account, room_id)
        return _toast(outcome, result.message)

    if action == "hang":
        if len(command.args) < 2:
            raise CommandError("Use '.tinytown hang <art_id>'.")
        room_id, _house = _owned_current_room(context, service)
        result = service.housing.hang_art(context.account, room_id, command.args[1])
        outcome = CommandOutcome(
            message=result.message,
            payload={"user": _user_payload(context), "decoration": {"bops_spent": result.bops_spent}},
            toast=False,
        )
        outcome.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=result.layout_event))
        if result.surface_event is not None:
            outcome.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=result.surface_event))
        if room_id == context.connection.room_id:
            outcome.snapshot = await context.rooms.build_snapshot(context.account, room_id)
        return _toast(outcome, result.message)

    if action == "help":
        districts = ", ".join(district.label for district in DISTRICTS_BY_ID.values())
        return CommandOutcome(
            message=(
                "Use '.tinytown list', '.tinytown buy <template>', '.tinytown enter <house>', "
                "'.tinytown household', '.tinytown decor', or '.tinytown artstore'. "
                f"Districts: {districts}."
            ),
            toast=False,
            log=False,
        )

    raise CommandError(
        "Unknown TinyTown command. Use list, buy, enter, visit, lock, household, npc, play, decor, floor, hang, or artstore."
    )


def _build_state(runtime: object) -> TinytownService:
    return TinytownService(runtime)


def register(api: object) -> None:
    """Register the TinyTown command and runtime service."""

    api.register_command(
        "tinytown",
        "Open TinyTown or manage houses, households, and home decoration.",
        tinytown_command,
        usage=".tinytown [list|buy|enter|visit|lock|household|npc|play|decor|floor|hang|artstore]",
        help=(
            "Open the TinyTown house browser. Buy a private multi-room home, visit other "
            "residents, customize household peeps, and hang art from the Art Market. "
            "Household peeps have Energy, Health, and Cleanliness and live autonomously."
        ),
        toast=False,
        log=False,
    )
    api.register_state_factory(_build_state)
