"""Persistent NPC peep room locations backed by the world database."""

from __future__ import annotations

import sqlite3

from server.content.worlds import PeepDefinition, WorldDefinition
from server.security import utc_now
from server.state.migrations import DatabaseHub


class PeepLocationRepository:
    """Tracks the current room of every NPC peep.

    The authored ``peep.room_id`` is the spawn default; rows in
    ``world.peep_locations`` override it once an NPC has moved. The map is kept
    in memory because room snapshots and behavior routing read it on every
    event, and only this repository writes it.
    """

    def __init__(self, hub: DatabaseHub, world: WorldDefinition) -> None:
        self._hub = hub
        self._rooms: dict[str, str] = {
            peep_id: peep.room_id
            for peep_id, peep in world.peeps.items()
            if peep.room_id in world.rooms
        }
        self._load(world)

    def _load(self, world: WorldDefinition) -> None:
        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT peep_id, room_id FROM world.peep_locations"
            ).fetchall()
        for row in rows:
            peep_id = str(row["peep_id"])
            room_id = str(row["room_id"])
            if peep_id in self._rooms and room_id in world.rooms:
                self._rooms[peep_id] = room_id

    @staticmethod
    def default_room(peep: PeepDefinition) -> str:
        """Return the authored spawn room for a peep."""

        return peep.room_id

    def room_for(self, peep_id: str) -> str | None:
        """Return the current room for a peep, if it is known."""

        return self._rooms.get(peep_id)

    def peep_ids_in(self, room_id: str) -> set[str]:
        """Return every peep whose current room is *room_id*."""

        return {peep_id for peep_id, current in self._rooms.items() if current == room_id}

    def set_in_transaction(self, connection: sqlite3.Connection, peep_id: str, room_id: str) -> None:
        """Persist a peep's room inside an already-open transaction."""

        connection.execute(
            """
            INSERT INTO world.peep_locations (peep_id, room_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(peep_id) DO UPDATE SET room_id = excluded.room_id, updated_at = excluded.updated_at
            """,
            (peep_id, room_id, utc_now().isoformat()),
        )

    def record(self, peep_id: str, room_id: str) -> None:
        """Update the in-memory map after a committed location write."""

        if peep_id in self._rooms:
            self._rooms[peep_id] = room_id
