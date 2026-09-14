"""World-state repository for shared room persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import sqlite3
import uuid

from server.content.worlds import WorldDefinition
from server.protocol import MAX_HISTORY_MESSAGES
from server.security import utc_now
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class RoomCardStack:
    """A persisted room card stack."""

    stack_id: str
    room_id: str
    card_def_id: str
    quantity: int
    pos_x: float
    pos_y: float
    pos_z: float
    scope: str
    pinned: bool
    initial_key: str | None
    created_at: str
    updated_at: str


class WorldStateRepository:
    """Repository for shared room state and room sequences."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    def _stack_from_row(self, row: sqlite3.Row) -> RoomCardStack:
        return RoomCardStack(
            stack_id=row["stack_id"],
            room_id=row["room_id"],
            card_def_id=row["card_def_id"],
            quantity=int(row["quantity"]),
            pos_x=float(row["pos_x"]),
            pos_y=float(row["pos_y"]),
            pos_z=float(row["pos_z"]),
            scope=row["scope"],
            pinned=bool(row["pinned"]),
            initial_key=row["initial_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def initialize_world(self, world: WorldDefinition) -> None:
        """Ensure all persisted room rows exist and overlay initial cards."""

        with self._hub.transaction() as connection:
            for room_id, room in world.rooms.items():
                connection.execute(
                    "INSERT OR IGNORE INTO world.rooms (room_id, seq, revision, chat_history_json) VALUES (?, 0, 0, '[]')",
                    (room_id,),
                )
                for initial_card in room.initial_cards:
                    seeded = connection.execute(
                        """
                        SELECT 1
                        FROM world.initial_room_cards
                        WHERE initial_key = ?
                        """,
                        (initial_card.initial_key,),
                    ).fetchone()
                    if seeded is not None:
                        continue
                    now = utc_now().isoformat()
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO world.room_cards (
                            stack_id, room_id, card_def_id, quantity, pos_x, pos_y, pos_z,
                            scope, pinned, initial_key, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'room', 0, ?, ?, ?)
                        """,
                        (
                            f"room:{initial_card.initial_key}",
                            room_id,
                            initial_card.card_id,
                            initial_card.quantity,
                            initial_card.pos[0],
                            initial_card.pos[1],
                            initial_card.pos[2],
                            initial_card.initial_key,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO world.initial_room_cards (
                            initial_key,
                            seeded_at
                        ) VALUES (?, ?)
                        """,
                        (initial_card.initial_key, now),
                    )

    def list_room_cards(self, room_id: str) -> list[RoomCardStack]:
        """Return persisted room cards for a room."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM world.room_cards WHERE room_id = ? ORDER BY created_at, stack_id",
                (room_id,),
            ).fetchall()
        return [self._stack_from_row(row) for row in rows]

    def get_room_seq(self, room_id: str) -> int:
        """Return the current room sequence."""

        with self._hub.locked() as connection:
            row = connection.execute("SELECT seq FROM world.rooms WHERE room_id = ?", (room_id,)).fetchone()
        return 0 if row is None else int(row["seq"])

    def get_chat_history(self, room_id: str) -> list[dict[str, Any]]:
        """Return recent room chat history."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT chat_history_json FROM world.rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return [] if row is None else list(json.loads(row["chat_history_json"]))

    def append_chat_message(self, room_id: str, entry: dict[str, Any]) -> int:
        """Persist a room chat message and advance the room sequence."""

        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT chat_history_json, seq FROM world.rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown room.")
            history = list(json.loads(row["chat_history_json"]))
            history.append(entry)
            history = history[-MAX_HISTORY_MESSAGES:]
            seq = int(row["seq"]) + 1
            connection.execute(
                "UPDATE world.rooms SET seq = ?, chat_history_json = ? WHERE room_id = ?",
                (seq, json.dumps(history), room_id),
            )
        return seq

    def advance_room_seq(self, connection: sqlite3.Connection, room_id: str, *, revision_delta: int = 0) -> int:
        """Advance a room sequence, optionally incrementing revision."""

        row = connection.execute("SELECT seq, revision FROM world.rooms WHERE room_id = ?", (room_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown room.")
        seq = int(row["seq"]) + 1
        revision = int(row["revision"]) + revision_delta
        connection.execute(
            "UPDATE world.rooms SET seq = ?, revision = ? WHERE room_id = ?",
            (seq, revision, room_id),
        )
        return seq

    def take_room_card(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        stack_id: str,
        quantity: int,
    ) -> tuple[RoomCardStack, bool, int]:
        """Remove quantity from a room stack and return the prior stack state."""

        row = connection.execute(
            "SELECT * FROM world.room_cards WHERE room_id = ? AND stack_id = ?",
            (room_id, stack_id),
        ).fetchone()
        if row is None:
            raise ValueError("That card is no longer in the room.")
        stack = self._stack_from_row(row)
        if stack.pinned:
            raise ValueError("That card stack is pinned in place.")
        if quantity < 1 or quantity > stack.quantity:
            raise ValueError("Invalid quantity for that room stack.")
        deleted = quantity == stack.quantity
        if deleted:
            connection.execute("DELETE FROM world.room_cards WHERE stack_id = ?", (stack_id,))
        else:
            connection.execute(
                """
                UPDATE world.room_cards
                SET quantity = quantity - ?, updated_at = ?
                WHERE stack_id = ?
                """,
                (quantity, utc_now().isoformat(), stack_id),
            )
        seq = self.advance_room_seq(connection, room_id, revision_delta=1)
        return stack, deleted, seq

    def add_room_card(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        card_def_id: str,
        quantity: int,
        pos: tuple[float, float, float],
        pinned: bool = False,
    ) -> tuple[RoomCardStack, int]:
        """Create a new room card stack and advance the room sequence."""

        stack_id = f"room:{uuid.uuid4()}"
        now = utc_now().isoformat()
        connection.execute(
            """
            INSERT INTO world.room_cards (
                stack_id, room_id, card_def_id, quantity, pos_x, pos_y, pos_z,
                scope, pinned, initial_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'room', ?, NULL, ?, ?)
            """,
            (stack_id, room_id, card_def_id, quantity, pos[0], pos[1], pos[2], int(pinned), now, now),
        )
        seq = self.advance_room_seq(connection, room_id, revision_delta=1)
        row = connection.execute("SELECT * FROM world.room_cards WHERE stack_id = ?", (stack_id,)).fetchone()
        return self._stack_from_row(row), seq
