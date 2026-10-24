"""Shared helpers for resolving and launching activities from commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.content.activities import ActivityDefinition
from server.content.surface_props import whiteboard_options


@dataclass(frozen=True, slots=True)
class ResolvedActivity:
    """An activity selected for launch."""

    definition: ActivityDefinition
    prop_instance_id: str | None = None


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
        if not peep.activity or context.rooms.peep_room(peep) != room_id:
            continue
        if peep.id.casefold() == key or peep.label.casefold() == key:
            definition = context.world.activities[peep.activity]
            return ResolvedActivity(definition=definition)
    room = context.world.rooms.get(room_id)
    if room is not None:
        for prop in context.rooms.props_in_room(room_id):
            activity = context.world.props[prop.prop_id].activity
            if activity and prop.id.casefold() == key:
                context.rooms.require_prop_target(room_id, prop.id)
                definition = context.world.activities[activity]
                return ResolvedActivity(
                    definition=definition,
                    prop_instance_id=prop.id,
                )
    definition = _find_definition(context.world.activities, key)
    if definition is None:
        raise CommandError("Unknown activity.")
    return ResolvedActivity(definition=definition)


def start_activity(
    context: CommandContext,
    resolved: ResolvedActivity,
    *,
    room_id: str,
    replace_existing: bool,
    extra_config: Mapping[str, object] | None = None,
) -> CommandOutcome:
    """Start a resolved activity and build the command outcome."""

    definition = resolved.definition
    if definition.required_feature and not context.activities.feature_enabled(definition.required_feature):
        raise CommandError(f"{definition.title} is not available.")
    if definition.rooms and room_id not in definition.rooms:
        raise CommandError(f"{definition.title} is not available here.")
    if definition.required_skill and not context.powers.has_power(context.account.id, "admin"):
        if not context.progression.has_slotted_skill(context.account, definition.required_skill):
            raise CommandError(
                f"Slot the {definition.required_skill.replace('-', ' ').title()} skill to use {definition.title}."
            )
    config: dict[str, object] = {
        "start_cost": definition.start_cost,
        "record": definition.record,
        "min_completed_round": definition.min_completed_round,
    }
    if resolved.prop_instance_id is not None:
        config["prop_instance_id"] = resolved.prop_instance_id
        if definition.id == "whiteboard":
            surface = context.rooms.surface_for(room_id, resolved.prop_instance_id, "whiteboard")
            if surface is not None:
                config["surface"] = surface.serialize()
                config["can_edit_surface"] = not surface.locked
            config["whiteboard_options"] = whiteboard_options()
    config.update(extra_config or {})
    try:
        session, replaced = context.activities.start(
            account_id=context.account.id,
            kind=definition.id,
            title=definition.title,
            room_id=room_id,
            replace_existing=replace_existing,
            config=config,
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
