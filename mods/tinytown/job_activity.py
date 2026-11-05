"""The `.jobs` command and Job Office activity bridge payloads."""

from __future__ import annotations

from mods.tinytown.job_runs import JobRuns
from server.commands.activity_launch import ResolvedActivity, start_activity
from server.commands.core import require_room_id
from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand, parse_target

MOD_ID = "tinytown"
ACTIVITY_KIND = "jobs"


def _service(context: CommandContext) -> JobRuns:
    service = context.mods.get(MOD_ID)
    jobs = getattr(service, "jobs", None)
    if not isinstance(jobs, JobRuns) or not jobs.available:
        raise CommandError("TinyTown Job Office is not available here.")
    return jobs


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id) or context.account
    return context.serialize_user(account)


def _outcome(payload: dict[str, object]) -> CommandOutcome:
    return CommandOutcome(message="", toast=False, log=False, payload=payload)


def _require_open(context: CommandContext) -> None:
    current = context.activities.get(context.account.id)
    if current is None or current.kind != ACTIVITY_KIND:
        raise CommandError("Open the Job Office before managing a shift.")


async def _open_activity(context: CommandContext) -> CommandOutcome:
    definition = context.world.activities.get(ACTIVITY_KIND)
    if definition is None:
        raise CommandError("The Job Office is unavailable.")
    return start_activity(
        context,
        ResolvedActivity(definition=definition),
        room_id=require_room_id(context),
        replace_existing=True,
        extra_config={"entry": "office"},
    )


def _helper_ids(args: tuple[str, ...]) -> list[str]:
    helper_ids: list[str] = []
    for token in args:
        if not token.startswith("@"):
            raise CommandError("Helpers must use @peep:<id>.")
        target = parse_target(token)
        if target.kind != "peep" or not target.value:
            raise CommandError("Helpers must use @peep:<id>.")
        helper_ids.append(target.value)
    return helper_ids


async def tinytown_jobs_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Open the Job Office or run its board/start/choose/resume/quit actions."""

    jobs = _service(context)
    if not command.args:
        return await _open_activity(context)
    action = command.args[0].lower()
    if action in {"open", "office"}:
        return await _open_activity(context)
    _require_open(context)

    if action == "board":
        return _outcome({"board": jobs.board(context.account)})

    if action == "start":
        if len(command.args) < 2:
            raise CommandError("Choose a job with '.jobs start <job_id>'.")
        job_id = command.args[1].strip()
        helper_ids = _helper_ids(command.args[2:])
        try:
            run = jobs.start(context.account, job_id, helper_ids)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None, "user": _user_payload(context)})

    if action == "challenge":
        helper_ids = _helper_ids(command.args[1:])
        if len(helper_ids) > 1:
            raise CommandError("Choose one roommate to lead the scene.")
        try:
            payload = jobs.challenge(context.account, helper_ids[0] if helper_ids else None)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome(payload)

    if action == "resolve":
        if len(command.args) < 4:
            raise CommandError("Use '.jobs resolve <challenge_id> <score> <elapsed_ms>'.")
        try:
            score = int(command.args[2])
            elapsed_ms = int(command.args[3])
        except (TypeError, ValueError) as exc:
            raise CommandError("Score and elapsed time must be whole numbers.") from exc
        try:
            result = jobs.resolve(context.account, command.args[1], score, elapsed_ms)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result["user"] = _user_payload(context)
        return _outcome(result)

    if action == "resume":
        try:
            run = jobs.resume(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": run, "outcome": None})

    if action == "quit":
        try:
            outcome = jobs.quit(context.account)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _outcome({"run": None, "outcome": outcome, "user": _user_payload(context)})

    raise CommandError("Use '.jobs [board|start|challenge|resolve|resume|quit]'.")
