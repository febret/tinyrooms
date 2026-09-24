"""Live-state reconciliation for world publishes.

Publishing replaces definition files. Reconciliation is intentionally minimal:
deleted rooms have their orphaned live rows removed, and newly defined or
uninitialized rooms are seeded. Surviving rooms are seed-only: once a room has
been initialized, later definition edits (props, seed cards, environment) do not
overwrite its live state. Inventories, progress, ownership, and occupancy are not
rewritten. A remembered room that no longer exists is coerced to the entry room
lazily by the room service, so occupants need no eager repair.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server.content.worlds import WorldDefinition
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


@dataclass(frozen=True, slots=True)
class DestructiveChange:
    """A publish change that discards definition content or live state."""

    kind: str
    room_id: str
    summary: str

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {"kind": self.kind, "room_id": self.room_id, "summary": self.summary}


@dataclass(slots=True)
class ReconcileResult:
    """Summary of a reconciliation pass."""

    deleted_rooms: tuple[str, ...] = ()
    removed_card_stacks: int = 0
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {
            "deleted_rooms": list(self.deleted_rooms),
            "removed_card_stacks": self.removed_card_stacks,
            "notes": list(self.notes),
        }


def destructive_changes(
    old_world: WorldDefinition,
    new_world: WorldDefinition,
) -> list[DestructiveChange]:
    """Return the definition removals a publish would apply.

    Only deleted rooms have live-state consequences: their orphaned card stacks
    and state rows are dropped. Removed exits and props in surviving rooms are
    definition-only edits; the editor treats surviving rooms as seed-only, so
    they do not touch or require confirmation against live state.
    """

    changes: list[DestructiveChange] = []
    for room_id in sorted(set(old_world.rooms) - set(new_world.rooms)):
        changes.append(
            DestructiveChange(
                kind="deleted_room",
                room_id=room_id,
                summary=f"Delete room '{old_world.rooms[room_id].label or room_id}'.",
            )
        )
    return changes


def affected_rooms(changes: list[DestructiveChange]) -> list[str]:
    """Return the sorted room ids touched by destructive changes."""

    return sorted({change.room_id for change in changes})


def reconcile(
    hub: DatabaseHub,
    world_state: WorldStateRepository,
    old_world: WorldDefinition,
    new_world: WorldDefinition,
) -> ReconcileResult:
    """Remove orphaned rows for deleted rooms and seed new rooms.

    Orphaned room card stacks belonging to deleted rooms are deleted outright;
    cards are not returned to their droppers. Rooms that survive keep their live
    cards, and uninitialized rooms are (re)seeded from the new definition.
    """

    deleted_rooms = sorted(set(old_world.rooms) - set(new_world.rooms))
    removed_stacks = 0
    if deleted_rooms:
        with hub.transaction() as connection:
            for room_id in deleted_rooms:
                removed_stacks += len(world_state.list_room_cards(room_id))
                world_state.delete_room_cards(connection, room_id)
                world_state.delete_room_state(connection, room_id)
    world_state.initialize_world(new_world)
    return ReconcileResult(
        deleted_rooms=tuple(deleted_rooms),
        removed_card_stacks=removed_stacks,
    )
