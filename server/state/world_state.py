"""World-state repository for shared room persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any
import sqlite3
import uuid

from server.content.worlds import InitialRoomCard, WorldDefinition
from server.protocol import MAX_HISTORY_MESSAGES
from server.security import utc_now
from server.state.migrations import DatabaseHub


PLAYER_ROOM_PREFIX = "bedroom:"


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


class LayoutRevisionConflict(ValueError):
    """Raised when a layout save is based on a stale revision."""


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
    placed_by_account_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerRoomRecord:
    """A persisted per-player bedroom, backed by a ``room_states`` row.

    ``door`` carries both the lock state and the validated customization:
    ``{"style": {...}, "locked": bool}``.
    """

    room_id: str
    owner_account_id: str
    door: dict[str, Any]


class WorldStateRepository:
    """Repository for shared room state, cards, and in-memory chat history."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub
        self._chat_history: dict[str, list[dict[str, Any]]] = {}
        self._chat_lock = threading.Lock()

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
            placed_by_account_id=row["placed_by_account_id"],
        )

    def _player_room_from_row(self, row: sqlite3.Row) -> PlayerRoomRecord:
        try:
            door = json.loads(row["door_json"])
        except (TypeError, ValueError):
            door = {}
        return PlayerRoomRecord(
            room_id=row["room_id"],
            owner_account_id=row["owner_account_id"],
            door=door if isinstance(door, dict) else {},
        )

    def list_player_rooms(self) -> list[PlayerRoomRecord]:
        """Return every persisted player room in creation order."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM world.room_states WHERE room_id LIKE ? ORDER BY rowid",
                (f"{PLAYER_ROOM_PREFIX}%",),
            ).fetchall()
        return [self._player_room_from_row(row) for row in rows]

    def get_player_room(self, room_id: str) -> PlayerRoomRecord | None:
        """Return a player room by its room id."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.room_states WHERE room_id = ? AND room_id LIKE ?",
                (room_id, f"{PLAYER_ROOM_PREFIX}%"),
            ).fetchone()
        return None if row is None else self._player_room_from_row(row)

    def get_player_room_for_account(self, account_id: str) -> PlayerRoomRecord | None:
        """Return the player room owned by an account, if any."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.room_states WHERE owner_account_id = ? AND room_id LIKE ? "
                "ORDER BY rowid LIMIT 1",
                (account_id, f"{PLAYER_ROOM_PREFIX}%"),
            ).fetchone()
        return None if row is None else self._player_room_from_row(row)

    def insert_player_room(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        owner_account_id: str,
        door: dict[str, Any],
    ) -> PlayerRoomRecord:
        """Create or claim the ``room_states`` row for a player room."""

        connection.execute(
            """
            INSERT INTO world.room_states (room_id, initialized, owner_account_id, props_json, door_json)
            VALUES (?, 0, ?, '{}', ?)
            ON CONFLICT(room_id) DO UPDATE SET
                owner_account_id = excluded.owner_account_id,
                door_json = excluded.door_json
            """,
            (room_id, owner_account_id, json.dumps(door)),
        )
        return PlayerRoomRecord(room_id=room_id, owner_account_id=owner_account_id, door=door)

    def update_player_room(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        door: dict[str, Any],
    ) -> None:
        """Update a player room's door customization and lock state."""

        cursor = connection.execute(
            "UPDATE world.room_states SET door_json = ? WHERE room_id = ? AND room_id LIKE ?",
            (json.dumps(door), room_id, f"{PLAYER_ROOM_PREFIX}%"),
        )
        if cursor.rowcount != 1:
            raise ValueError("That bedroom no longer exists.")

    @staticmethod
    def _mark_room_initialized(connection: sqlite3.Connection, room_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM world.room_states WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO world.room_states (room_id, initialized, owner_account_id, props_json)
                VALUES (?, 1, NULL, '{}')
                """,
                (room_id,),
            )
        else:
            connection.execute(
                "UPDATE world.room_states SET initialized = 1 WHERE room_id = ?",
                (room_id,),
            )

    def initialize_world(self, world: WorldDefinition) -> None:
        """Seed any room whose definition has not been loaded into the world yet."""

        with self._hub.transaction() as connection:
            for room_id, room in world.rooms.items():
                if room.template:
                    continue
                row = connection.execute(
                    "SELECT initialized FROM world.room_states WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
                if row is not None and int(row["initialized"]) == 1:
                    continue
                connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))
                self._insert_seed_cards(connection, room_id, room.initial_cards)
                self._mark_room_initialized(connection, room_id)
                self._seed_room_layout(connection, room_id, room, world)

    def reset_room_cards(
        self,
        room_id: str,
        initial_cards: tuple[InitialRoomCard, ...],
    ) -> list[RoomCardStack]:
        """Replace all live room cards with the definition seed cards."""

        with self._hub.transaction() as connection:
            connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))
            stacks = self._insert_seed_cards(connection, room_id, initial_cards)
            self._mark_room_initialized(connection, room_id)
        return stacks

    def seed_player_room(self, room_id: str, room, world: WorldDefinition) -> None:
        """Initialize a dynamically created room from its definition."""

        with self._hub.transaction() as connection:
            connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))
            self._insert_seed_cards(connection, room_id, room.initial_cards)
            self._mark_room_initialized(connection, room_id)
            self._seed_room_layout(connection, room_id, room, world)

    @staticmethod
    def _seed_room_layout(
        connection: sqlite3.Connection,
        room_id: str,
        room,
        world: WorldDefinition,
    ) -> None:
        """Seed the editable prop instances from the room definition."""

        props = [
            {
                "id": instance.id,
                "prop_id": instance.prop_id,
                "position": list(instance.pos),
                "rotation": list(instance.rot),
                "scale": float(instance.scale),
            }
            for instance in room.props.values()
            if world.props[instance.prop_id].editable
        ]
        connection.execute(
            "UPDATE world.room_states SET props_json = ? WHERE room_id = ?",
            (json.dumps(props), room_id),
        )

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

    def list_room_cards_all(self) -> list[RoomCardStack]:
        """Return every persisted room card stack across all rooms."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM world.room_cards ORDER BY room_id, created_at, stack_id"
            ).fetchall()
        return [self._stack_from_row(row) for row in rows]

    def delete_room_cards(self, connection: sqlite3.Connection, room_id: str) -> None:
        """Delete every live card stack in a room."""

        connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))

    def delete_room_state(self, connection: sqlite3.Connection, room_id: str) -> None:
        """Delete a room's live state row, if present."""

        connection.execute("DELETE FROM world.room_states WHERE room_id = ?", (room_id,))

    def read_world_meta(self, key: str) -> str | None:
        """Return a world metadata value, or None when unset."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT value FROM world.world_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["value"])

    def write_world_meta(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        """Upsert a world metadata value."""

        connection.execute(
            """
            INSERT INTO world.world_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def read_room_view(self, room_id: str) -> tuple[list[RoomCardStack], list[dict[str, Any]]]:
        """Return the room cards and in-memory chat history."""

        with self._hub.locked() as connection:
            card_rows = connection.execute(
                "SELECT * FROM world.room_cards WHERE room_id = ? ORDER BY created_at, stack_id",
                (room_id,),
            ).fetchall()
        cards = [self._stack_from_row(card) for card in card_rows]
        return cards, self.get_chat_history(room_id)

    def read_room_environment(self, room_id: str) -> tuple[dict[str, Any], int]:
        """Return a room's persisted environment and layout revision."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT environment_json, layout_revision FROM world.room_states WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        if row is None:
            return {}, 0
        try:
            environment = json.loads(row["environment_json"])
        except (TypeError, ValueError):
            environment = {}
        return (environment if isinstance(environment, dict) else {}), int(row["layout_revision"])

    def write_room_environment(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        environment: dict[str, Any],
        revision: int,
    ) -> None:
        """Persist a room's environment and layout revision."""

        cursor = connection.execute(
            """
            UPDATE world.room_states
            SET environment_json = ?, layout_revision = ?
            WHERE room_id = ?
            """,
            (json.dumps(environment), int(revision), room_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("That room is not initialized.")

    def read_room_layout(self, room_id: str) -> dict[str, Any]:
        """Return a room's live prop layout and revision.

        ``props`` is ``None`` until the room has a saved layout, letting callers
        fall back to the YAML definition.
        """

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT props_json, layout_revision FROM world.room_states WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        if row is None:
            return {"revision": 0, "props": None}
        try:
            parsed = json.loads(row["props_json"])
        except (TypeError, ValueError):
            parsed = None
        return {
            "revision": int(row["layout_revision"]),
            "props": parsed if isinstance(parsed, list) else None,
        }

    def write_room_layout(
        self,
        connection: sqlite3.Connection,
        room_id: str,
        props: list[dict[str, Any]],
        environment: dict[str, Any],
        *,
        expected_revision: int,
    ) -> int:
        """Compare-and-swap a room's layout, environment, and revision."""

        new_revision = int(expected_revision) + 1
        cursor = connection.execute(
            """
            UPDATE world.room_states
            SET props_json = ?, environment_json = ?, layout_revision = ?
            WHERE room_id = ? AND layout_revision = ?
            """,
            (
                json.dumps(props),
                json.dumps(environment),
                new_revision,
                room_id,
                int(expected_revision),
            ),
        )
        if cursor.rowcount != 1:
            raise LayoutRevisionConflict("The room layout changed since you loaded it.")
        return new_revision

    def get_chat_history(self, room_id: str) -> list[dict[str, Any]]:
        """Return the in-memory chat history for a room.

        Chat history is process-local and intentionally lost on server restart.
        """

        with self._chat_lock:
            return list(self._chat_history.get(room_id, []))

    def append_chat_message(self, room_id: str, entry: dict[str, Any]) -> None:
        """Append an in-memory room chat message, capped at the history limit."""

        with self._chat_lock:
            history = self._chat_history.setdefault(room_id, [])
            history.append(entry)
            del history[:-MAX_HISTORY_MESSAGES]

    def take_room_card(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        stack_id: str,
        quantity: int,
    ) -> tuple[RoomCardStack, bool]:
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
        return stack, deleted

    def add_room_card(
        self,
        connection: sqlite3.Connection,
        *,
        room_id: str,
        card_def_id: str,
        quantity: int,
        pos: tuple[float, float, float],
        pinned: bool = False,
        placed_by_account_id: str | None = None,
    ) -> RoomCardStack:
        """Create a new room card stack."""

        stack_id = f"room:{uuid.uuid4()}"
        now = utc_now().isoformat()
        position = (float(pos[0]), float(pos[1]), float(pos[2]))
        connection.execute(
            """
            INSERT INTO world.room_cards (
                stack_id, room_id, card_def_id, quantity, position_json,
                scope, pinned, created_at, updated_at, placed_by_account_id
            ) VALUES (?, ?, ?, ?, ?, 'room', ?, ?, ?, ?)
            """,
            (
                stack_id,
                room_id,
                card_def_id,
                quantity,
                json.dumps(list(position)),
                int(pinned),
                now,
                now,
                placed_by_account_id,
            ),
        )
        return RoomCardStack(
            stack_id=stack_id,
            room_id=room_id,
            card_def_id=card_def_id,
            quantity=quantity,
            position=position,
            scope="room",
            pinned=pinned,
            created_at=now,
            updated_at=now,
            placed_by_account_id=placed_by_account_id,
        )
