"""Validation for moving an NPC peep through a room exit."""

from __future__ import annotations

from dataclasses import dataclass

from server.content.worlds import PeepDefinition, WorldDefinition


@dataclass(frozen=True, slots=True)
class NpcMove:
    """A validated NPC room change."""

    peep_id: str
    label: str
    exit_id: str
    source_room_id: str
    destination_room_id: str
    direction: str


def resolve_npc_move(
    world: WorldDefinition,
    peep: PeepDefinition,
    source_room_id: str,
    exit_id: str,
) -> NpcMove:
    """Resolve an NPC exit traversal or raise ``ValueError``.

    NPCs cannot cross exits flagged ``npc_barrier`` or locked doors. Card
    requirements do not apply because NPCs hold no inventory.
    """

    source_room = world.rooms.get(source_room_id)
    if source_room is None:
        raise ValueError("That peep is not in a known room.")
    exit_definition = source_room.exits.get(exit_id)
    if exit_definition is None:
        raise ValueError("That exit is not available from this room.")
    if exit_definition.npc_barrier:
        raise ValueError("That way is blocked for peeps.")
    if exit_definition.locked:
        raise ValueError("That way is locked.")
    destination_room = world.rooms.get(exit_definition.target_room_id)
    if destination_room is None:
        raise ValueError("That exit leads nowhere.")
    return NpcMove(
        peep_id=peep.id,
        label=peep.label,
        exit_id=exit_id,
        source_room_id=source_room_id,
        destination_room_id=destination_room.id,
        direction=exit_definition.label,
    )
