"""Shared profile and account repository for Tinyrooms."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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

SESSION_TOUCH_INTERVAL_SECONDS = 60.0


def _default_profile() -> dict[str, object]:
    return {
        "friends": [],
        "friend_requests_sent": [],
        "friend_requests_received": [],
        "pinned_peeps": [],
        "skills": [],
        "statuses": [],
        "show_activity_log": False,
        "ui_settings": {},
    }


def _normalize_profile(raw: object) -> dict[str, object]:
    defaults = _default_profile()
    if not isinstance(raw, dict):
        return defaults
    merged: dict[str, object] = dict(defaults)
    for key, value in raw.items():
        merged[key] = value
    if not isinstance(merged.get("friends"), list):
        merged["friends"] = []
    if not isinstance(merged.get("friend_requests_sent"), list):
        merged["friend_requests_sent"] = []
    if not isinstance(merged.get("friend_requests_received"), list):
        merged["friend_requests_received"] = []
    if not isinstance(merged.get("pinned_peeps"), list):
        merged["pinned_peeps"] = []
    if not isinstance(merged.get("skills"), list):
        merged["skills"] = []
    if not isinstance(merged.get("statuses"), list):
        merged["statuses"] = []
    if not isinstance(merged.get("show_activity_log"), bool):
        merged["show_activity_log"] = False
    if not isinstance(merged.get("ui_settings"), dict):
        merged["ui_settings"] = {}
    return merged


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """A stored account record."""

    id: str
    username_display: str
    username_key: str
    password_hash: str
    sticker: str | None
    initial_sticker_complete: bool
    level: int
    kudos: int
    bops: int
    shared_energy: float
    last_energy_at: str
    last_daily_claim: str | None
    active_session_generation: int
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
class UserProfileRecord:
    """A persisted per-user profile row."""

    account_id: str
    last_world_id: str
    remembered_room: str | None
    native_cards: dict[str, object]
    counters: dict[str, object]
    buffs: dict[str, object]
    tasks: dict[str, object]
    memories: dict[str, object]
    ownership: dict[str, object]
    profile: dict[str, object]
    last_visit_at: str

    @property
    def owned_rooms(self) -> tuple[str, ...]:
        raw = self.ownership.get("rooms")
        return tuple(str(room_id) for room_id in raw) if isinstance(raw, list) else ()

    @property
    def friends(self) -> tuple[str, ...]:
        raw = self.profile.get("friends")
        return tuple(raw) if isinstance(raw, list) else ()

    @property
    def show_activity_log(self) -> bool:
        return bool(self.profile.get("show_activity_log", False))

    @property
    def pinned_peeps(self) -> tuple[str, ...]:
        raw = self.profile.get("pinned_peeps")
        return tuple(raw) if isinstance(raw, list) else ()

    @property
    def skills(self) -> tuple[str | None, ...]:
        raw = self.profile.get("skills")
        if not isinstance(raw, list):
            return ()
        return tuple(str(entry) if isinstance(entry, str) else None for entry in raw)

    @property
    def active_statuses(self) -> tuple[str, ...]:
        raw = self.profile.get("statuses")
        if not isinstance(raw, list):
            return ()
        return tuple(str(entry) for entry in raw)


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
            level=int(row["level"]),
            kudos=int(row["kudos"]),
            bops=int(row["bops"]),
            shared_energy=float(row["shared_energy"]),
            last_energy_at=row["last_energy_at"],
            last_daily_claim=row["last_daily_claim"],
            active_session_generation=int(row["active_session_generation"]),
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

    def _user_profile_from_row(self, row: sqlite3.Row) -> UserProfileRecord:
        return UserProfileRecord(
            account_id=row["account_id"],
            last_world_id=row["last_world_id"],
            remembered_room=row["remembered_room"],
            native_cards=json.loads(row["native_cards_json"]),
            counters=json.loads(row["counters_json"]),
            buffs=json.loads(row["buffs_json"]),
            tasks=json.loads(row["tasks_json"]),
            memories=json.loads(row["memories_json"]),
            ownership=json.loads(row["ownership_json"]),
            profile=_normalize_profile(json.loads(row["profile_json"])),
            last_visit_at=row["last_visit_at"],
        )

    def get_account_by_id(self, account_id: str) -> AccountRecord | None:
        """Fetch an account by ID."""

        with self._hub.locked() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else self._account_from_row(row)

    def get_accounts_by_ids(self, account_ids: list[str]) -> dict[str, AccountRecord]:
        """Fetch multiple accounts by ID with a single query."""

        unique_ids = list(dict.fromkeys(account_ids))
        if not unique_ids:
            return {}
        placeholders = ", ".join("?" for _ in unique_ids)
        with self._hub.locked() as connection:
            rows = connection.execute(
                f"SELECT * FROM accounts WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
        return {row["id"]: self._account_from_row(row) for row in rows}

    def get_account_by_username(self, username: str) -> AccountRecord | None:
        """Fetch an account by normalized username."""

        _, username_key = normalize_username(username)
        with self._hub.locked() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE username_key = ?", (username_key,)).fetchone()
        return None if row is None else self._account_from_row(row)

    def resolve_account(self, identifier: str) -> AccountRecord | None:
        """Fetch an account by ID first, then by normalized username."""

        return self.get_account_by_id(identifier) or self.get_account_by_username(identifier)

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
                    initial_sticker_complete, level, kudos, bops,
                    shared_energy, last_energy_at, last_daily_claim,
                    active_session_generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 0, 0, 0, 10, 80, ?, NULL, 0, ?, ?)
                """,
                (
                    account_id,
                    display_name,
                    username_key,
                    password_digest,
                    now,
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
                INSERT INTO user_profiles (
                    account_id, last_world_id, remembered_room, native_cards_json,
                    counters_json, buffs_json, tasks_json, memories_json,
                    ownership_json, profile_json, last_visit_at
                ) VALUES (?, ?, ?, '{}', ?, '{}', '{}', '{}', '{}', ?, ?)
                """,
                (
                    account_id,
                    world_id,
                    entry_room,
                    json.dumps(STARTING_WORLD_COUNTERS),
                    json.dumps(_default_profile()),
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
        """Update the session last-seen time, at most once per touch interval."""

        token_hash = hash_session_token(token)
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT last_seen_at FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return
        now = utc_now()
        try:
            last_seen = datetime.fromisoformat(row["last_seen_at"])
        except (ValueError, TypeError):
            last_seen = None
        if last_seen is not None and last_seen.tzinfo is not None:
            if (now - last_seen).total_seconds() < SESSION_TOUCH_INTERVAL_SECONDS:
                return
        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now.isoformat(), token_hash),
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
            updated_stacks.append(
                InventoryStack(
                    stack_id=current.stack_id,
                    account_id=current.account_id,
                    world_id=current.world_id,
                    card_def_id=current.card_def_id,
                    quantity=current.quantity + add_here,
                    scope=current.scope,
                    equipped=current.equipped,
                    pinned=current.pinned,
                    created_at=current.created_at,
                    updated_at=now,
                )
            )
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
            updated_stacks.append(
                InventoryStack(
                    stack_id=stack_id,
                    account_id=account_id,
                    world_id=world_id,
                    card_def_id=card_def_id,
                    quantity=add_here,
                    scope=scope,
                    equipped=False,
                    pinned=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            remaining -= add_here
        return updated_stacks

    def set_stack_equipped(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        world_id: str,
        stack_id: str,
        equipped: bool,
    ) -> None:
        """Set the equipped flag on a visible inventory stack."""

        cursor = connection.execute(
            """
            UPDATE profile_card_stacks SET equipped = ?, updated_at = ?
            WHERE account_id = ? AND stack_id = ? AND (world_id IS NULL OR world_id = ?)
            """,
            (1 if equipped else 0, utc_now().isoformat(), account_id, stack_id, world_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("That card stack is not in your inventory.")

    def create_inventory_stack(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        world_id: str | None,
        card_def_id: str,
        quantity: int,
        scope: str,
        equipped: bool = False,
    ) -> InventoryStack:
        """Insert a brand-new inventory stack without merging into existing ones."""

        now = utc_now().isoformat()
        stack_id = f"inv:{uuid.uuid4()}"
        connection.execute(
            """
            INSERT INTO profile_card_stacks (
                stack_id, account_id, world_id, card_def_id, quantity, scope,
                equipped, pinned, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                stack_id,
                account_id,
                world_id,
                card_def_id,
                quantity,
                scope,
                1 if equipped else 0,
                now,
                now,
            ),
        )
        return InventoryStack(
            stack_id=stack_id,
            account_id=account_id,
            world_id=world_id,
            card_def_id=card_def_id,
            quantity=quantity,
            scope=scope,
            equipped=equipped,
            pinned=False,
            created_at=now,
            updated_at=now,
        )

    def set_stack_quantity(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        stack_id: str,
        quantity: int,
    ) -> None:
        """Set an absolute quantity on an owned stack, deleting it at zero."""

        if quantity < 0:
            raise ValueError("Stack quantity cannot be negative.")
        if quantity == 0:
            connection.execute(
                "DELETE FROM profile_card_stacks WHERE account_id = ? AND stack_id = ?",
                (account_id, stack_id),
            )
            return
        cursor = connection.execute(
            "UPDATE profile_card_stacks SET quantity = ?, updated_at = ? WHERE account_id = ? AND stack_id = ?",
            (quantity, utc_now().isoformat(), account_id, stack_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("That card stack is not in your inventory.")

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
        return (
            InventoryStack(
                stack_id=stack.stack_id,
                account_id=stack.account_id,
                world_id=stack.world_id,
                card_def_id=stack.card_def_id,
                quantity=stack.quantity - quantity,
                scope=stack.scope,
                equipped=stack.equipped,
                pinned=stack.pinned,
                created_at=stack.created_at,
                updated_at=now,
            ),
            False,
        )

    def get_user_profile(self, account_id: str) -> UserProfileRecord | None:
        """Fetch the single per-user profile row."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM user_profiles WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return None if row is None else self._user_profile_from_row(row)

    def user_profile_for(self, account_id: str, world_id: str, entry_room: str) -> UserProfileRecord:
        """Return the current profile, creating or refreshing it only when needed."""

        profile = self.get_user_profile(account_id)
        if profile is None or profile.last_world_id != world_id:
            profile = self.ensure_user_profile(account_id, world_id, entry_room)
        return profile

    def ensure_user_profile(self, account_id: str, world_id: str, entry_room: str) -> UserProfileRecord:
        """Ensure the single per-user profile row exists and return it."""

        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM user_profiles WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO user_profiles (
                        account_id, last_world_id, remembered_room, native_cards_json,
                        counters_json, buffs_json, tasks_json, memories_json,
                        ownership_json, profile_json, last_visit_at
                    ) VALUES (?, ?, ?, '{}', ?, '{}', '{}', '{}', '{}', ?, ?)
                    """,
                    (
                        account_id,
                        world_id,
                        entry_room,
                        json.dumps(STARTING_WORLD_COUNTERS),
                        json.dumps(_default_profile()),
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM user_profiles WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
            elif row["last_world_id"] != world_id:
                connection.execute(
                    """
                    UPDATE user_profiles
                    SET last_world_id = ?, remembered_room = ?, last_visit_at = ?
                    WHERE account_id = ?
                    """,
                    (world_id, entry_room, now, account_id),
                )
                row = connection.execute(
                    "SELECT * FROM user_profiles WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
        return self._user_profile_from_row(row)

    def set_remembered_room(self, connection: sqlite3.Connection, account_id: str, world_id: str, room_id: str) -> None:
        """Persist the user's remembered room and last visited world."""

        connection.execute(
            """
            UPDATE user_profiles
            SET last_world_id = ?, remembered_room = ?, last_visit_at = ?
            WHERE account_id = ?
            """,
            (world_id, room_id, utc_now().isoformat(), account_id),
        )

    def update_account_progress(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        *,
        level: int,
        kudos: int,
        bops: int,
        energy: float,
        last_energy_at: str,
        last_daily_claim: str | None,
    ) -> AccountRecord:
        """Persist shared account progression fields inside a transaction."""

        connection.execute(
            """
            UPDATE accounts
            SET level = ?, kudos = ?, bops = ?, shared_energy = ?, last_energy_at = ?,
                last_daily_claim = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(level),
                int(kudos),
                int(bops),
                float(energy),
                last_energy_at,
                last_daily_claim,
                utc_now().isoformat(),
                account_id,
            ),
        )
        row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account_from_row(row)

    def update_progress(
        self,
        connection: sqlite3.Connection,
        account: AccountRecord,
        *,
        level: int | None = None,
        kudos: int | None = None,
        bops: int | None = None,
        energy: float | None = None,
        last_energy_at: str | None = None,
        last_daily_claim: str | None = None,
    ) -> AccountRecord:
        """Persist progression fields, keeping the account's current value for omitted fields."""

        return self.update_account_progress(
            connection,
            account.id,
            level=account.level if level is None else level,
            kudos=account.kudos if kudos is None else kudos,
            bops=account.bops if bops is None else bops,
            energy=account.shared_energy if energy is None else energy,
            last_energy_at=account.last_energy_at if last_energy_at is None else last_energy_at,
            last_daily_claim=account.last_daily_claim if last_daily_claim is None else last_daily_claim,
        )

    def write_counters(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        counters: dict[str, object],
    ) -> None:
        """Persist the world-scoped counter values for a user."""

        connection.execute(
            "UPDATE user_profiles SET counters_json = ? WHERE account_id = ?",
            (json.dumps(counters), account_id),
        )

    def write_buffs(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        buffs: list[dict[str, object]],
    ) -> None:
        """Persist active buff instances for a user."""

        connection.execute(
            "UPDATE user_profiles SET buffs_json = ? WHERE account_id = ?",
            (json.dumps({"instances": buffs}), account_id),
        )

    def update_profile(
        self,
        account_id: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> UserProfileRecord:
        """Apply a mutation to the free-form profile JSON and return the result."""

        with self._hub.transaction() as connection:
            return self._update_profile_json(connection, account_id, mutate)

    def update_profile_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> UserProfileRecord:
        """Apply a profile JSON mutation inside an existing transaction."""

        return self._update_profile_json(connection, account_id, mutate)

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

    def _update_profile_json(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> UserProfileRecord:
        row = connection.execute(
            "SELECT * FROM user_profiles WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown account.")
        profile = _normalize_profile(json.loads(row["profile_json"]))
        mutate(profile)
        connection.execute(
            "UPDATE user_profiles SET profile_json = ? WHERE account_id = ?",
            (json.dumps(profile), account_id),
        )
        updated = connection.execute(
            "SELECT * FROM user_profiles WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return self._user_profile_from_row(updated)

    def set_show_activity_log(
        self,
        account_id: str,
        visible: bool,
    ) -> UserProfileRecord:
        """Persist Action Log visibility and return the updated user profile."""

        with self._hub.transaction() as connection:

            def _set_visible(profile: dict[str, object]) -> None:
                profile["show_activity_log"] = bool(visible)

            return self._update_profile_json(connection, account_id, _set_visible)
