"""Shared helpers for resolving and launching activities from commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.content.activities import ActivityDefinition


@dataclass(frozen=True, slots=True)
class ResolvedActivity:
    """An activity selected for launch and its effective room binding."""

    definition: ActivityDefinition
    room_bound: bool


def _find_definition(
    activities: Mapping[str, ActivityDefinition],
    target: str,
) -> ActivityDefinition | None:
    for definition in activities.values():
        if definition.id.casefold() == target:
            return definition
        if any(alias.casefold() == target for alias in definition.aliases):
            return definition
    return None


def resolve_activity(context: CommandContext, room_id: str, target: str) -> ResolvedActivity:
    """Resolve a `.play` target against peeps, props, and the activity catalog."""

    key = target.casefold()
    for peep in context.world.peeps.values():
        if peep.room_id != room_id or not peep.activity:
            continue
        if peep.id.casefold() == key or peep.label.casefold() == key:
            definition = context.world.activities[peep.activity]
            return ResolvedActivity(definition=definition, room_bound=True)
    room = context.world.rooms.get(room_id)
    if room is not None:
        for prop in room.props.values():
            if prop.activity and prop.id.casefold() == key:
                definition = context.world.activities[prop.activity]
                return ResolvedActivity(definition=definition, room_bound=True)
    definition = _find_definition(context.world.activities, key)
    if definition is None:
        raise CommandError("Unknown activity.")
    return ResolvedActivity(definition=definition, room_bound=definition.room_bound)


def start_activity(
    context: CommandContext,
    resolved: ResolvedActivity,
    *,
    room_id: str,
    replace_existing: bool,
) -> CommandOutcome:
    """Start a resolved activity and build the command outcome."""

    definition = resolved.definition
    if definition.required_feature and not context.activities.feature_enabled(definition.required_feature):
        raise CommandError(f"{definition.title} is not available.")
    if definition.rooms and room_id not in definition.rooms:
        raise CommandError(f"{definition.title} is not available here.")
    try:
        session, replaced = context.activities.start(
            account_id=context.account.id,
            kind=definition.id,
            title=definition.title,
            room_bound=resolved.room_bound,
            room_id=room_id if resolved.room_bound else None,
            replace_existing=replace_existing,
        )
    except ValueError as exc:
        raise CommandError(
            f"{exc} Retry with '.play {definition.id} replace' to replace it."
        ) from exc
    private_events = []
    if replaced is not None:
        private_events.append(
            {
                "type": "activity.closed",
                "activity": context.activities.serialize(replaced),
                "reason": "replaced",
            }
        )
    private_events.append(
        {"type": "activity.started", "activity": context.activities.serialize(session)}
    )
    return CommandOutcome(
        message=f"{definition.title} opened.",
        payload={"activity": context.activities.serialize(session)},
        private_events=private_events,
    )
