"""Behavior intents that change an NPC's room."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import sqlite3

from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import WorldDefinition
from server.protocol import peep_enter_event, peep_leave_event
from server.services.sprite_rooms import SpriteService
from server.state.npc_peep_states import NpcPeepStateRepository


def apply_move_peep(
    *,
    world: WorldDefinition,
    peep_states: NpcPeepStateRepository | None,
    sprites: SpriteService | None,
    current_room: Callable[[str], str | None],
    connection: sqlite3.Connection,
    payload: Mapping[str, object],
    result: object,
    deferred: list[object],
    log: Callable[..., None],
) -> None:
    """Move an NPC directly between rooms and queue ordered room events."""

    peep_id = str(payload.get("peep_id", ""))
    destination_room_id = str(payload.get("room_id", ""))
    peep = world.peeps.get(peep_id)
    destination_room = world.rooms.get(destination_room_id)
    if peep is None or destination_room is None:
        log("behavior.intent.skipped", kind="move_peep", reason="unknown")
        return
    if peep_states is None:
        log("behavior.intent.skipped", kind="move_peep", reason="unavailable")
        return
    source_room_id = current_room(peep_id) or peep.room_id
    if source_room_id == destination_room_id:
        return
    peep_states.set_in_transaction(connection, peep_id, destination_room_id)
    if sprites is not None:
        sprites.forget_npc(peep_id)
    source_room = world.rooms.get(source_room_id)
    if source_room is not None:
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=source_room_id,
                event=peep_leave_event(
                    peep_id=peep.id,
                    label=peep.label,
                    room_id=source_room_id,
                    destination_room_id=destination_room_id,
                    direction="a doorway",
                ),
            )
        )
    result.room_broadcasts.append(
        PendingRoomBroadcast(
            room_id=destination_room_id,
            event=peep_enter_event(
                peep_id=peep.id,
                label=peep.label,
                room_id=destination_room_id,
                source_room_id=source_room_id,
                source_room_label=source_room.label if source_room is not None else None,
            ),
        )
    )

    def record_move() -> None:
        peep_states.record(peep_id, destination_room_id)

    deferred.append(record_move)
