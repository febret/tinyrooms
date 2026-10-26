"""Tiny Vault mod: the `.heist` command and runtime heist director."""

from __future__ import annotations

from mods.tinyvault.heist import HeistResult, HeistService, MOD_ID
from server.commands.activity_launch import ResolvedActivity, start_activity
from server.commands.core import require_room_id
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
    merge_behavior_result,
)
from server.commands.parser import ParsedCommand, parse_target


def _service(context: CommandContext) -> HeistService:
    service = context.mods.get(MOD_ID)
    if not isinstance(service, HeistService) or not service.available:
        raise CommandError("Tiny Vault heists are not available here.")
    return service


def _fresh_user(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


def _outcome(context: CommandContext, result: HeistResult) -> CommandOutcome:
    # The .heist command is registered toast=False so generic acknowledgements
    # stay silent; every success message therefore needs an explicit toast or
    # the command looks dead. Add one unless the result already toasts.
    private_events = list(result.private_events)
    if result.message and not any(event.get("type") == "toast" for event in private_events):
        private_events.append({"type": "toast", "tone": "success", "text": result.message})
    outcome = CommandOutcome(
        message=result.message,
        payload=dict(result.payload),
        private_events=private_events,
        room_broadcasts=list(result.room_broadcasts),
    )
    if result.navigation is not None:
        navigation = result.navigation
        outcome.snapshot = navigation.destination_snapshot
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.source_room_id, event=navigation.source_event)
        )
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.destination_room_id, event=navigation.destination_event)
        )
        if navigation.closed_activity is not None:
            outcome.private_events.append(
                {"type": "activity.closed", "activity": navigation.closed_activity, "reason": "room_changed"}
            )
        for behavior in navigation.behavior_results:
            merge_behavior_result(context, outcome, behavior)
    if result.refresh_user:
        outcome.payload = {**(outcome.payload or {}), "user": _fresh_user(context)}
    return outcome


def _optional_prop_token(args: tuple[str, ...]) -> str | None:
    for token in args:
        if token.startswith("@prop:"):
            return parse_target(token).value
    return None


def _parse_result_args(args: tuple[str, ...]) -> tuple[bool, float]:
    success = False
    seconds = 0.0
    for token in args:
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip().lower()
        value = value.strip().lower()
        if key == "success":
            success = value in {"1", "true", "yes", "success"}
        elif key in {"time", "seconds"}:
            try:
                seconds = float(value)
            except ValueError as exc:
                raise CommandError("Time must be a number of seconds.") from exc
    return success, seconds


async def _open_board(context: CommandContext, service: HeistService, room_id: str) -> CommandOutcome:
    definition = context.world.activities.get("heist-board")
    if definition is None:
        raise CommandError("The job board is unavailable.")
    payload = await service.board_payload(context.account.id)
    return start_activity(
        context,
        ResolvedActivity(definition=definition),
        room_id=room_id,
        replace_existing=True,
        extra_config={"board": payload},
    )


async def heist_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Run Tiny Vault crew, tool, vault, escape, and heat commands."""

    service = _service(context)
    room_id = require_room_id(context)
    try:
        if not command.args:
            if room_id == "hideout":
                return await _open_board(context, service, room_id)
            return _outcome(context, HeistResult(payload={"status": await service.status_payload()}, message="Heist status loaded."))
        action = command.args[0].lower()
        rest = command.args[1:]

        if action in {"jobs", "job", "list"}:
            board = await service.board_payload(context.account.id)
            jobs = board["jobs"] if isinstance(board.get("jobs"), list) else []
            open_jobs = [job for job in jobs if not job.get("locked")]
            result = HeistResult(
                payload={"board": board},
                message=f"{len(open_jobs)} of {len(jobs)} jobs available at heat {board.get('heat', 0)}.",
            )
            result.private_events.append(
                {"type": "toast", "tone": "info", "text": result.message or "Job board loaded."}
            )
            return _outcome(context, result)
        if action == "board":
            return await _open_board(context, service, room_id)
        if action in {"shop", "loadout", "tools"}:
            board = await service.board_payload(context.account.id)
            tools = board["tools"] if isinstance(board.get("tools"), list) else []
            owned = sum(1 for tool in tools if tool.get("owned"))
            result = HeistResult(
                payload={"board": board},
                message=f"Loadout: {owned} of {len(tools)} tools owned.",
            )
            result.private_events.append(
                {"type": "toast", "tone": "info", "text": result.message or "Loadout loaded."}
            )
            return _outcome(context, result)
        if action == "status":
            status = await service.status_payload()
            if status.get("active"):
                crew = status["crew"] if isinstance(status.get("crew"), list) else []
                text = (
                    f"{status.get('label')}: {status.get('phase')}, "
                    f"alarm {status.get('alarm')}, {len(crew)} crew."
                )
            else:
                text = "No active heist. Start one from the job board."
            result = HeistResult(payload={"status": status}, message=text)
            result.private_events.append({"type": "toast", "tone": "info", "text": text})
            return _outcome(context, result)
        if action == "heat":
            heat = await service.heat_payload(context.account.id)
            level = int(heat.get("heat", 0))
            history = heat["history"] if isinstance(heat.get("history"), list) else []
            if level <= 0:
                text = "Heat 0. The city barely knows your name."
            elif level == 1:
                text = "Heat 1. Patrols have a sketch that might be you."
            elif level == 2:
                text = "Heat 2. The fence is shredding your photos nightly."
            else:
                text = f"Heat {level}. Only the hardest jobs will have you now."
            if history and isinstance(history[-1], dict):
                text += f" Last score: {history[-1].get('job_id')} ({history[-1].get('result')})."
            text += " Lay low with '.heist laylow' (25 Bops)."
            result = HeistResult(payload={"heat": heat}, message=text)
            result.private_events.append({"type": "toast", "tone": "info", "text": text})
            return _outcome(context, result)
        if action == "start":
            if not rest:
                raise CommandError("Use '.heist start <job_id>'.")
            return _outcome(context, await service.start_job(context.account, room_id, rest[0]))
        if action == "join":
            return _outcome(context, await service.join_job(context.account, room_id))
        if action == "leave":
            return _outcome(context, await service.leave_job(context.account))
        if action == "abort":
            return _outcome(context, await service.abort_job(context.account))
        if action == "enter":
            return _outcome(context, await service.enter_job(context.account, room_id))
        if action == "buy":
            if not rest:
                raise CommandError("Use '.heist buy <tool>'.")
            return _outcome(context, await service.buy_tool(context.account, room_id, rest[0]))
        if action == "bot":
            if not rest:
                raise CommandError("Use '.heist bot <lookout|muscle|slicer>'.")
            return _outcome(context, await service.hire_bot(context.account, room_id, rest[0]))
        if action == "use":
            if len(rest) < 1:
                raise CommandError("Use '.heist use <tool> [@prop:<id>]'.")
            return _outcome(
                context, await service.use_tool(context.account, room_id, rest[0], _optional_prop_token(rest[1:]))
            )
        if action == "hack":
            prop = _optional_prop_token(rest)
            if prop is None:
                raise CommandError("Use '.heist hack @prop:<id>'.")
            return _outcome(context, await service.hack_console(context.account, room_id, prop))
        if action == "loot":
            prop = _optional_prop_token(rest)
            if prop is None:
                raise CommandError("Use '.heist loot @prop:<id>'.")
            return _outcome(context, await service.loot_prop(context.account, room_id, prop))
        if action == "safecrack":
            return _outcome(context, await service.open_safecrack(context.account, room_id))
        if action == "safecrack_result":
            success, seconds = _parse_result_args(rest)
            return _outcome(context, await service.safecrack_result(context.account, room_id, success, seconds))
        if action == "escape":
            return _outcome(context, await service.escape_job(context.account, room_id))
        if action == "laylow":
            return _outcome(context, await service.lay_low(context.account))
        raise CommandError("Unknown heist command. Try '.heist jobs'.")
    except ValueError as exc:
        raise CommandError(str(exc)) from exc


def _build_state(runtime: object) -> HeistService:
    return HeistService(runtime)


def register(api: object) -> None:
    """Register the Tiny Vault command and runtime state factory."""

    api.register_command(
        "heist",
        "Run Tiny Vault heists.",
        heist_command,
        usage=".heist <jobs|board|start|join|enter|buy|use|hack|loot|safecrack|escape|abort|heat|laylow> ...",
        help="Plan crews, buy tools, infiltrate the bank, crack the vault, and escape before lockdown.",
        toast=False,
        log=False,
    )
    api.register_state_factory(_build_state)
