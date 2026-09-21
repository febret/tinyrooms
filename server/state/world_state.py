"""World-state repository for shared room persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import sqlite3
import uuid

from server.content.worlds import InitialRoomCard, WorldDefinition
from server.protocol import MAX_HISTORY_MESSAGES
from server.security import utc_now
from server.state.migrations import DatabaseHub


def _position_from_json(raw: str) -> tuple[float, float, float]:
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        return (50.0, 50.0, 0.0)
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return (50.0, 50.0, 0.0)
    try:
        return (float(values[0]), float(values[1]), float(values[2]))
    except (ValueError, TypeError):
        return (50.0, 50.0, 0.0)


@dataclass(frozen=True, slots=True)
class RoomCardStack:
    """A persisted room card stack."""

    stack_id: str
    room_id: str
    card_def_id: str
    quantity: int
    position: tuple[float, float, float]
    scope: str
    pinned: bool
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
            position=_position_from_json(row["position_json"]),
            scope=row["scope"],
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def initialize_world(self, world: WorldDefinition) -> None:
        """Create missing rooms and seed their initial cards exactly once."""

        with self._hub.transaction() as connection:
            for room_id, room in world.rooms.items():
                exists = connection.execute(
                    "SELECT 1 FROM world.rooms WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
                if exists is not None:
                    continue
                connection.execute(
                    "INSERT INTO world.rooms (room_id, seq, revision, chat_history_json) VALUES (?, 0, 0, '[]')",
                    (room_id,),
                )
                self._insert_seed_cards(connection, room_id, room.initial_cards)

    def reset_room_cards(
        self,
        room_id: str,
        initial_cards: tuple[InitialRoomCard, ...],
    ) -> tuple[list[RoomCardStack], int]:
        """Replace all live room cards with the definition seed cards."""

        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM world.rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown room.")
            connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))
            stacks = self._insert_seed_cards(connection, room_id, initial_cards)
            seq = self.advance_room_seq(connection, room_id)
        return stacks, seq

    @staticmethod
    def _insert_seed_cards(
        connection: sqlite3.Connection,
        room_id: str,
        initial_cards: tuple[InitialRoomCard, ...],
    ) -> list[RoomCardStack]:
        """Insert definition seed cards with deterministic stack IDs."""

        now = utc_now().isoformat()
        stacks: list[RoomCardStack] = []
        for initial_card in initial_cards:
            stack_id = f"room:{initial_card.initial_key}"
            position = (
                float(initial_card.pos[0]),
                float(initial_card.pos[1]),
                float(initial_card.pos[2]),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO world.room_cards (
                    stack_id, room_id, card_def_id, quantity, position_json,
                    scope, pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'room', 0, ?, ?)
                """,
                (
                    stack_id,
                    room_id,
                    initial_card.card_id,
                    initial_card.quantity,
                    json.dumps(list(position)),
                    now,
                    now,
                ),
            )
            stacks.append(
                RoomCardStack(
                    stack_id=stack_id,
                    room_id=room_id,
                    card_def_id=initial_card.card_id,
                    quantity=initial_card.quantity,
                    position=position,
                    scope="room",
                    pinned=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        return stacks

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

    def read_room_view(self, room_id: str) -> tuple[int, list[RoomCardStack], list[dict[str, Any]]]:
        """Return the room sequence, cards, and chat history from a single consistent read."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT seq, chat_history_json FROM world.rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if row is None:
                return 0, [], []
            card_rows = connection.execute(
                "SELECT * FROM world.room_cards WHERE room_id = ? ORDER BY created_at, stack_id",
                (room_id,),
            ).fetchall()
            return int(row["seq"]), [self._stack_from_row(card) for card in card_rows], list(json.loads(row["chat_history_json"]))

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

    def advance_room_seq(self, connection: sqlite3.Connection, room_id: str) -> int:
        """Advance the room sequence used for ordering room broadcasts."""

        row = connection.execute("SELECT seq FROM world.rooms WHERE room_id = ?", (room_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown room.")
        seq = int(row["seq"]) + 1
        connection.execute(
            "UPDATE world.rooms SET seq = ? WHERE room_id = ?",
            (seq, room_id),
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
        seq = self.advance_room_seq(connection, room_id)
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
        position = (float(pos[0]), float(pos[1]), float(pos[2]))
        connection.execute(
            """
            INSERT INTO world.room_cards (
                stack_id, room_id, card_def_id, quantity, position_json,
                scope, pinned, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'room', ?, ?, ?)
            """,
            (stack_id, room_id, card_def_id, quantity, json.dumps(list(position)), int(pinned), now, now),
        )
        seq = self.advance_room_seq(connection, room_id)
        return (
            RoomCardStack(
                stack_id=stack_id,
                room_id=room_id,
                card_def_id=card_def_id,
                quantity=quantity,
                position=position,
                scope="room",
                pinned=pinned,
                created_at=now,
                updated_at=now,
            ),
            seq,
        )
