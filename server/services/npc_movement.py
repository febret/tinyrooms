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

    NPCs cannot cross exits flagged ``npc_barrier``, locked doors, or exits that
    require a card. NPCs hold no inventory, so a keyed exit is always closed to
    them.
    """

    source_room = world.rooms.get(source_room_id)
    if source_room is None:
        raise ValueError("That peep is not in a known room.")
    exit_definition = source_room.exits.get(exit_id)
    if exit_definition is None:
        raise ValueError("That exit is not available from this room.")
    if exit_definition.npc_barrier:
        raise ValueError("That way is blocked for peeps.")
    if exit_definition.target_world_id is not None:
        raise ValueError("Peeps cannot cross into another world.")
    if exit_definition.locked:
        raise ValueError("That way is locked.")
    if exit_definition.requires_card_id is not None:
        raise ValueError("That way needs a key.")
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
