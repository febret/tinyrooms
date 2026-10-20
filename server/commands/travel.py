"""Outcome helpers shared by room and cross-world travel commands."""

from __future__ import annotations

from server.commands.outcomes import (
    CommandContext,
    CommandOutcome,
    PendingRoomBroadcast,
    merge_behavior_result,
)
from server.services.rooms import NavigationResult, WorldDeparture


def navigation_outcome(
    context: CommandContext,
    navigation: NavigationResult,
    *,
    message: str,
    payload: dict[str, object] | None = None,
) -> CommandOutcome:
    """Build the command outcome for a completed in-world room move."""

    outcome = CommandOutcome(
        message=message,
        payload=payload or {"room_id": navigation.destination_room_id},
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


def departure_outcome(
    context: CommandContext,
    departure: WorldDeparture,
    payload: dict[str, object],
    *,
    message: str,
) -> CommandOutcome:
    """Build the command outcome for leaving a room toward another world."""

    outcome = CommandOutcome(message=message, payload=payload)
    outcome.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=departure.source_room_id,
            event=departure.source_event,
        )
    )
    if departure.closed_activity is not None:
        outcome.private_events.append(
            {
                "type": "activity.closed",
                "activity": departure.closed_activity,
                "reason": "room_changed",
            }
        )
    for behavior in departure.behavior_results:
        merge_behavior_result(context, outcome, behavior)
    return outcome
