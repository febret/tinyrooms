"""The `.hack` command and Hacker Collective bridge payloads."""

from __future__ import annotations

from mods.tinytown.hacker_runs import CENTRAL_NODE, HackerRuns
from server.commands.activity_launch import ResolvedActivity, start_activity
from server.commands.core import require_room_id
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand, parse_target

MOD_ID = "tinytown"
ACTIVITY_KIND = "hacker"
USAGE = ".hack [board|start <corp> [floor] [@peep:<id>]|enter <node>|leave|answer <screen> <ms> <key=value,...>|challenge|resolve <node> <id> <score> <ms>|resume|quit]"


def _service(context: CommandContext) -> HackerRuns:
    service = context.mods.get(MOD_ID)
    hacker = getattr(service, "hacker", None)
    if not isinstance(hacker, HackerRuns) or not hacker.available:
        raise CommandError("The Hacker Collective is not available here.")
    return hacker


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


def _outcome(payload: dict[str, object]) -> CommandOutcome:
    return CommandOutcome(message="", toast=False, log=False, payload=payload)


def _require_open(context: CommandContext) -> None:
    current = context.activities.get(context.account.id)
    if current is None or current.kind != ACTIVITY_KIND:
        raise CommandError("Open the Hacker Collective before hacking a megacorp.")


async def _open_activity(context: CommandContext) -> CommandOutcome:
    definition = context.world.activities.get(ACTIVITY_KIND)
    if definition is None:
        raise CommandError("The Hacker Collective is unavailable.")
    return start_activity(
        context,
        ResolvedActivity(definition=definition),
        room_id=require_room_id(context),
        replace_existing=True,
        extra_config={"entry": "collective"},
    )


def _helper_id(args: tuple[str, ...]) -> str | None:
    helper_ids: list[str] = []
    for token in args:
        if not token.startswith("@"):
            raise CommandError("A roommate must use @peep:<id>.")
        target = parse_target(token)
        if target.kind != "peep" or not target.value:
            raise CommandError("A roommate must use @peep:<id>.")
        helper_ids.append(target.value)
    if len(helper_ids) > 1:
        raise CommandError("Bring at most one roommate.")
    return helper_ids[0] if helper_ids else None


def _answers(raw: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for chunk in raw.split(","):
        if not chunk:
            continue
        if "=" not in chunk:
            raise CommandError("Answers use key=value pairs separated by commas.")
        key, value = chunk.split("=", 1)
        key = key.strip()
        if not key:
            raise CommandError("Answers use key=value pairs separated by commas.")
        entries[key] = value.strip()
    if not entries:
        raise CommandError("Send at least one answer.")
    return entries


def _int(value: str, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{label} must be a whole number.") from exc


async def tinytown_hack_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open the Hacker Collective or drive one node, screen, or reflex challenge."""

    hacker = _service(context)
    if not command.args:
        return await _open_activity(context)
    action = command.args[0].lower()
    if action in {"open", "collective"}:
        return await _open_activity(context)
    _require_open(context)

    if action == "board":
        return _outcome({"board": hacker.board(context.account)})

    if action == "start":
        if len(command.args) < 2:
            raise CommandError("Choose a megacorp with '.hack start <corp> [floor]'.")
        args = list(command.args[2:])
        floor_level = None
        if args and args[0].isdigit():
            floor_level = int(args.pop(0))
        helper_id = _helper_id(tuple(args))
        try:
            run = hacker.start(context.account, command.args[1].strip(), helper_id, floor_level)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None})

    if action in {"leave", "back", "map"}:
        try:
            run = hacker.leave(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None})

    if action == "resume":
        try:
            run = hacker.resume(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None})

    if action == "enter":
        if len(command.args) < 2:
            raise CommandError("Choose a node with '.hack enter <node>'.")
        try:
            run = hacker.enter(context.account, command.args[1].strip())
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None})

    if action == "answer":
        if len(command.args) < 4:
            raise CommandError("Use '.hack answer <screen> <elapsed_ms> <key=value,...>'.")
        answers = _answers(" ".join(command.args[3:]))
        elapsed_ms = _int(command.args[2], "Elapsed time")
        try:
            result = hacker.answer(context.account, command.args[1].strip(), elapsed_ms, answers)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome(result)

    if action == "challenge":
        try:
            result = hacker.challenge(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome(result)

    if action == "resolve":
        if len(command.args) < 5:
            raise CommandError("Use '.hack resolve <node> <challenge_id> <score> <elapsed_ms>'.")
        node_id = command.args[1].strip()
        if node_id not in {CENTRAL_NODE} and not node_id.startswith("n"):
            raise CommandError("That is not a node id.")
        score = _int(command.args[3], "Score")
        elapsed_ms = _int(command.args[4], "Elapsed time")
        try:
            result = hacker.resolve(context.account, node_id, command.args[2].strip(), score, elapsed_ms)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result["user"] = _user_payload(context)
        return _outcome(result)

    if action == "quit":
        try:
            result = hacker.quit(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result["user"] = _user_payload(context)
        return _outcome(result)

    raise CommandError(f"Use {USAGE}.")
