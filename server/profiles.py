"""Shared profile and account repository for Tinyrooms."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import uuid

from server.security import (
    IssuedSession,
    create_session,
    hash_password,
    hash_session_token,
    normalize_username,
    utc_now,
)
from server.state.migrations import DatabaseHub


STARTING_GLOBAL_CARDS = ("smile", "sigh", "growl", "goof")
STARTING_FAVORITES = ("room", "emotes", "inventory")
STARTING_WORLD_COUNTERS = {
    "health": 50,
    "max_health": 50,
    "cleanliness": 100,
    "max_cleanliness": 100,
    "constitution": 1,
    "dexterity": 1,
    "charisma": 1,
    "fanciness": 1,
}


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """A stored account record."""

    id: str
    username_display: str
    username_key: str
    password_hash: str
    sticker: str | None
    initial_sticker_complete: bool
    favorites: tuple[str, ...]
    level: int
    kudos: int
    bops: int
    shared_energy: int
    last_energy_at: str
    last_daily_claim: str | None
    friends: tuple[str, ...]
    pending_friends: tuple[str, ...]
    active_session_generation: int
    show_activity_log: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """A stored authenticated session."""

    token_hash: str
    account_id: str
    csrf_token: str
    generation: int
    created_at: str
    expires_at: str
    last_seen_at: str
    account: AccountRecord


@dataclass(frozen=True, slots=True)
class InventoryStack:
    """A persisted inventory card stack."""

    stack_id: str
    account_id: str
    world_id: str | None
    card_def_id: str
    quantity: int
    scope: str
    equipped: bool
    pinned: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorldProfileRecord:
    """A persisted per-world profile row."""

    account_id: str
    world_id: str
    remembered_room: str | None
    native_cards: dict[str, object]
    counters: dict[str, object]
    buffs: dict[str, object]
    tasks: dict[str, object]
    memories: dict[str, object]
    ownership: dict[str, object]
    last_visit_at: str


class ProfileRepository:
    """Repository for account, session, inventory, and world-profile data."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    def _account_from_row(self, row: sqlite3.Row) -> AccountRecord:
        return AccountRecord(
            id=row["id"],
            username_display=row["username_display"],
            username_key=row["username_key"],
            password_hash=row["password_hash"],
            sticker=row["sticker"],
            initial_sticker_complete=bool(row["initial_sticker_complete"]),
            favorites=tuple(json.loads(row["favorites_json"])),
            level=int(row["level"]),
            kudos=int(row["kudos"]),
            bops=int(row["bops"]),
            shared_energy=int(row["shared_energy"]),
            last_energy_at=row["last_energy_at"],
            last_daily_claim=row["last_daily_claim"],
            friends=tuple(json.loads(row["friends_json"])),
            pending_friends=tuple(json.loads(row["pending_friends_json"])),
            active_session_generation=int(row["active_session_generation"]),
            show_activity_log=bool(row["show_activity_log"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _stack_from_row(self, row: sqlite3.Row) -> InventoryStack:
        return InventoryStack(
            stack_id=row["stack_id"],
            account_id=row["account_id"],
            world_id=row["world_id"],
            card_def_id=row["card_def_id"],
            quantity=int(row["quantity"]),
            scope=row["scope"],
            equipped=bool(row["equipped"]),
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _world_profile_from_row(self, row: sqlite3.Row) -> WorldProfileRecord:
        return WorldProfileRecord(
            account_id=row["account_id"],
            world_id=row["world_id"],
            remembered_room=row["remembered_room"],
            native_cards=json.loads(row["native_cards_json"]),
            counters=json.loads(row["counters_json"]),
            buffs=json.loads(row["buffs_json"]),
            tasks=json.loads(row["tasks_json"]),
            memories=json.loads(row["memories_json"]),
            ownership=json.loads(row["ownership_json"]),
            last_visit_at=row["last_visit_at"],
        )

    def get_account_by_id(self, account_id: str) -> AccountRecord | None:
        """Fetch an account by ID."""

        with self._hub.locked() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else self._account_from_row(row)

    def get_account_by_username(self, username: str) -> AccountRecord | None:
        """Fetch an account by normalized username."""

        _, username_key = normalize_username(username)
        with self._hub.locked() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE username_key = ?", (username_key,)).fetchone()
        return None if row is None else self._account_from_row(row)

    def create_account(self, username: str, password: str, world_id: str, entry_room: str) -> AccountRecord:
        """Create an account with default starting state."""

        display_name, username_key = normalize_username(username)
        now = utc_now().isoformat()
        account_id = str(uuid.uuid4())
        password_digest = hash_password(password)
        with self._hub.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM accounts WHERE username_key = ?",
                (username_key,),
            ).fetchone()
            if existing is not None:
                raise ValueError("That username is already taken.")
            connection.execute(
                """
                INSERT INTO accounts (
                    id, username_display, username_key, password_hash, sticker,
                    initial_sticker_complete, favorites_json, level, kudos, bops,
                    shared_energy, last_energy_at, last_daily_claim, friends_json,
                    pending_friends_json, active_session_generation, show_activity_log,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 0, ?, 0, 0, 10, 80, ?, NULL, ?, ?, 0, 0, ?, ?)
                """,
                (
                    account_id,
                    display_name,
                    username_key,
                    password_digest,
                    json.dumps(list(STARTING_FAVORITES)),
                    now,
                    json.dumps([]),
                    json.dumps([]),
                    now,
                    now,
                ),
            )
            for card_id in STARTING_GLOBAL_CARDS:
                connection.execute(
                    """
                    INSERT INTO profile_card_stacks (
                        stack_id, account_id, world_id, card_def_id, quantity, scope,
                        equipped, pinned, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, 1, 'global', 0, 0, ?, ?)
                    """,
                    (f"global:{account_id}:{card_id}", account_id, card_id, now, now),
                )
            connection.execute(
                """
                INSERT INTO world_profiles (
                    account_id, world_id, remembered_room, native_cards_json,
                    counters_json, buffs_json, tasks_json, memories_json,
                    ownership_json, last_visit_at
                ) VALUES (?, ?, ?, '{}', ?, '{}', '{}', '{}', '{}', ?)
                """,
                (
                    account_id,
                    world_id,
                    entry_room,
                    json.dumps(STARTING_WORLD_COUNTERS),
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account_from_row(row)

    def get_session_by_token(self, token: str) -> SessionRecord | None:
        """Fetch a session and its owning account by plaintext token."""

        with self._hub.locked() as connection:
            row = connection.execute(
                """
                SELECT
                    s.token_hash AS session_token_hash,
                    s.account_id AS session_account_id,
                    s.csrf_token AS session_csrf_token,
                    s.generation AS session_generation,
                    s.created_at AS session_created_at,
                    s.expires_at AS session_expires_at,
                    s.last_seen_at AS session_last_seen_at,
                    a.*
                FROM sessions AS s
                JOIN accounts AS a ON a.id = s.account_id
                WHERE s.token_hash = ?
                """,
                (hash_session_token(token),),
            ).fetchone()
        if row is None:
            return None
        account = self._account_from_row(row)
        return SessionRecord(
            token_hash=row["session_token_hash"],
            account_id=row["session_account_id"],
            csrf_token=row["session_csrf_token"],
            generation=int(row["session_generation"]),
            created_at=row["session_created_at"],
            expires_at=row["session_expires_at"],
            last_seen_at=row["session_last_seen_at"],
            account=account,
        )

    def issue_session(self, account_id: str) -> tuple[IssuedSession, int]:
        """Revoke prior sessions and issue a new one."""

        issued = create_session()
        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
            connection.execute(
                "UPDATE accounts SET active_session_generation = active_session_generation + 1, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            generation = int(
                connection.execute(
                    "SELECT active_session_generation FROM accounts WHERE id = ?",
                    (account_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO sessions (
                    token_hash, account_id, csrf_token, generation,
                    created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issued.token_hash,
                    account_id,
                    issued.csrf_token,
                    generation,
                    now,
                    issued.expires_at.isoformat(),
                    now,
                ),
            )
        return issued, generation

    def revoke_session(self, token: str) -> None:
        """Delete a session by plaintext token."""

        with self._hub.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(token),))

    def touch_session(self, token: str) -> None:
        """Update the session last-seen time."""

        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (utc_now().isoformat(), hash_session_token(token)),
            )

    def session_generation_matches(self, account_id: str, generation: int) -> bool:
        """Return whether a connection generation is still active."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT active_session_generation FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return row is not None and int(row[0]) == generation

    def list_inventory(self, account_id: str, world_id: str) -> list[InventoryStack]:
        """List global and current-world inventory stacks."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                """
                SELECT * FROM profile_card_stacks
                WHERE account_id = ? AND (world_id IS NULL OR world_id = ?)
                ORDER BY scope, created_at, stack_id
                """,
                (account_id, world_id),
            ).fetchall()
        return [self._stack_from_row(row) for row in rows]

    def get_inventory_stack(self, account_id: str, world_id: str, stack_id: str) -> InventoryStack | None:
        """Fetch a visible inventory stack by ID."""

        with self._hub.locked() as connection:
            row = connection.execute(
                """
                SELECT * FROM profile_card_stacks
                WHERE account_id = ? AND stack_id = ? AND (world_id IS NULL OR world_id = ?)
                """,
                (account_id, stack_id, world_id),
            ).fetchone()
        return None if row is None else self._stack_from_row(row)

    def add_inventory_card(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        world_id: str | None,
        card_def_id: str,
        quantity: int,
        scope: str,
        stack_limit: int,
    ) -> list[InventoryStack]:
        """Add cards to inventory while respecting the definition stack limit."""

        now = utc_now().isoformat()
        remaining = quantity
        updated_stacks: list[InventoryStack] = []
        rows = connection.execute(
            """
            SELECT * FROM profile_card_stacks
            WHERE account_id = ? AND card_def_id = ? AND COALESCE(world_id, '') = COALESCE(?, '')
              AND scope = ? AND equipped = 0 AND pinned = 0
            ORDER BY created_at, stack_id
            """,
            (account_id, card_def_id, world_id, scope),
        ).fetchall()
        for row in rows:
            if remaining <= 0:
                break
            current = self._stack_from_row(row)
            free_space = stack_limit - current.quantity
            if free_space <= 0:
                continue
            add_here = min(remaining, free_space)
            connection.execute(
                "UPDATE profile_card_stacks SET quantity = quantity + ?, updated_at = ? WHERE stack_id = ?",
                (add_here, now, current.stack_id),
            )
            updated = connection.execute(
                "SELECT * FROM profile_card_stacks WHERE stack_id = ?",
                (current.stack_id,),
            ).fetchone()
            updated_stacks.append(self._stack_from_row(updated))
            remaining -= add_here
        while remaining > 0:
            add_here = min(remaining, stack_limit)
            stack_id = f"inv:{uuid.uuid4()}"
            connection.execute(
                """
                INSERT INTO profile_card_stacks (
                    stack_id, account_id, world_id, card_def_id, quantity, scope,
                    equipped, pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (stack_id, account_id, world_id, card_def_id, add_here, scope, now, now),
            )
            created = connection.execute(
                "SELECT * FROM profile_card_stacks WHERE stack_id = ?",
                (stack_id,),
            ).fetchone()
            updated_stacks.append(self._stack_from_row(created))
            remaining -= add_here
        return updated_stacks

    def remove_inventory_quantity(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        world_id: str,
        stack_id: str,
        quantity: int,
    ) -> tuple[InventoryStack, bool]:
        """Remove quantity from an owned stack and report whether it was deleted."""

        row = connection.execute(
            """
            SELECT * FROM profile_card_stacks
            WHERE account_id = ? AND stack_id = ? AND (world_id IS NULL OR world_id = ?)
            """,
            (account_id, stack_id, world_id),
        ).fetchone()
        if row is None:
            raise ValueError("That card stack is not in your inventory.")
        stack = self._stack_from_row(row)
        if stack.pinned:
            raise ValueError("Pinned cards cannot be dropped.")
        if quantity < 1 or quantity > stack.quantity:
            raise ValueError("Invalid quantity for that card stack.")
        if quantity == stack.quantity:
            connection.execute("DELETE FROM profile_card_stacks WHERE stack_id = ?", (stack_id,))
            return stack, True
        now = utc_now().isoformat()
        connection.execute(
            "UPDATE profile_card_stacks SET quantity = quantity - ?, updated_at = ? WHERE stack_id = ?",
            (quantity, now, stack_id),
        )
        updated = connection.execute(
            "SELECT * FROM profile_card_stacks WHERE stack_id = ?",
            (stack_id,),
        ).fetchone()
        return self._stack_from_row(updated), False

    def get_world_profile(self, account_id: str, world_id: str) -> WorldProfileRecord | None:
        """Fetch the current world profile."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world_profiles WHERE account_id = ? AND world_id = ?",
                (account_id, world_id),
            ).fetchone()
        return None if row is None else self._world_profile_from_row(row)

    def ensure_world_profile(self, account_id: str, world_id: str, entry_room: str) -> WorldProfileRecord:
        """Ensure a world-profile row exists and return it."""

        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM world_profiles WHERE account_id = ? AND world_id = ?",
                (account_id, world_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO world_profiles (
                        account_id, world_id, remembered_room, native_cards_json,
                        counters_json, buffs_json, tasks_json, memories_json,
                        ownership_json, last_visit_at
                    ) VALUES (?, ?, ?, '{}', ?, '{}', '{}', '{}', '{}', ?)
                    """,
                    (
                        account_id,
                        world_id,
                        entry_room,
                        json.dumps(STARTING_WORLD_COUNTERS),
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM world_profiles WHERE account_id = ? AND world_id = ?",
                    (account_id, world_id),
                ).fetchone()
        return self._world_profile_from_row(row)

    def set_remembered_room(self, connection: sqlite3.Connection, account_id: str, world_id: str, room_id: str) -> None:
        """Persist the user's remembered room."""

        connection.execute(
            """
            UPDATE world_profiles
            SET remembered_room = ?, last_visit_at = ?
            WHERE account_id = ? AND world_id = ?
            """,
            (room_id, utc_now().isoformat(), account_id, world_id),
        )

    def set_sticker(self, account_id: str, sticker_name: str) -> AccountRecord:
        """Persist the user's initial sticker choice."""

        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown account.")
            account = self._account_from_row(row)
            if account.initial_sticker_complete and account.sticker == sticker_name:
                return account
            if account.initial_sticker_complete and account.sticker != sticker_name:
                raise ValueError("Initial sticker has already been confirmed.")
            connection.execute(
                """
                UPDATE accounts
                SET sticker = ?, initial_sticker_complete = 1, updated_at = ?
                WHERE id = ?
                """,
                (sticker_name, now, account_id),
            )
            updated = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account_from_row(updated)

    def toggle_favorite(self, account_id: str, card_id: str) -> AccountRecord:
        """Toggle a core-card favorite and return the updated account."""

        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown account.")
            account = self._account_from_row(row)
            favorites = list(account.favorites)
            if card_id in favorites:
                favorites.remove(card_id)
            else:
                favorites.append(card_id)
            connection.execute(
                "UPDATE accounts SET favorites_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(favorites), now, account_id),
            )
            updated = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account_from_row(updated)

    def set_show_activity_log(
        self,
        account_id: str,
        visible: bool,
    ) -> AccountRecord:
        """Persist Action Log visibility and return the updated account."""

        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            result = connection.execute(
                """
                UPDATE accounts
                SET show_activity_log = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(visible), now, account_id),
            )
            if result.rowcount != 1:
                raise ValueError("Unknown account.")
            updated = connection.execute(
                "SELECT * FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return self._account_from_row(updated)
