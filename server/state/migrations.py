"""SQLite schema initialization and validation for profile and world-state databases."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading


PROFILE_SCHEMA_VERSION = 1
WORLD_SCHEMA_VERSION = 4

_PROFILE_SCHEMA_SQL = """
BEGIN;
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username_display TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    sticker TEXT,
    initial_sticker_complete INTEGER NOT NULL DEFAULT 0 CHECK (initial_sticker_complete IN (0, 1)),
    favorites_json TEXT NOT NULL CHECK (json_valid(favorites_json)),
    level INTEGER NOT NULL DEFAULT 0 CHECK (level >= 0),
    kudos INTEGER NOT NULL DEFAULT 0 CHECK (kudos >= 0),
    bops INTEGER NOT NULL DEFAULT 10 CHECK (bops >= 0),
    shared_energy INTEGER NOT NULL DEFAULT 80 CHECK (shared_energy >= 0),
    last_energy_at TEXT NOT NULL,
    last_daily_claim TEXT,
    friends_json TEXT NOT NULL CHECK (json_valid(friends_json)),
    pending_friends_json TEXT NOT NULL CHECK (json_valid(pending_friends_json)),
    active_session_generation INTEGER NOT NULL DEFAULT 0 CHECK (active_session_generation >= 0),
    show_activity_log INTEGER NOT NULL DEFAULT 0 CHECK (show_activity_log IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    generation INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_account_id ON sessions(account_id);
CREATE TABLE IF NOT EXISTS profile_card_stacks (
    stack_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    world_id TEXT,
    card_def_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    scope TEXT NOT NULL CHECK (scope IN ('global', 'world')),
    equipped INTEGER NOT NULL DEFAULT 0 CHECK (equipped IN (0, 1)),
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profile_cards_owner ON profile_card_stacks(account_id, world_id);
CREATE INDEX IF NOT EXISTS idx_profile_cards_lookup ON profile_card_stacks(account_id, card_def_id, scope);
CREATE TABLE IF NOT EXISTS world_profiles (
    account_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    remembered_room TEXT,
    native_cards_json TEXT NOT NULL CHECK (json_valid(native_cards_json)),
    counters_json TEXT NOT NULL CHECK (json_valid(counters_json)),
    buffs_json TEXT NOT NULL CHECK (json_valid(buffs_json)),
    tasks_json TEXT NOT NULL CHECK (json_valid(tasks_json)),
    memories_json TEXT NOT NULL CHECK (json_valid(memories_json)),
    ownership_json TEXT NOT NULL CHECK (json_valid(ownership_json)),
    last_visit_at TEXT NOT NULL,
    PRIMARY KEY (account_id, world_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_world_profiles_world ON world_profiles(world_id);
PRAGMA user_version = 1;
COMMIT;
"""

_WORLD_SCHEMA_SQL = """
BEGIN;
CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL DEFAULT 0 CHECK (seq >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    chat_history_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(chat_history_json))
);
CREATE TABLE IF NOT EXISTS room_cards (
    stack_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    card_def_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    pos_x REAL NOT NULL,
    pos_y REAL NOT NULL,
    pos_z REAL NOT NULL,
    scope TEXT NOT NULL DEFAULT 'room',
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_room_cards_room_id ON room_cards(room_id);
CREATE INDEX IF NOT EXISTS idx_room_cards_order ON room_cards(room_id, created_at, stack_id);
CREATE TABLE IF NOT EXISTS prop_states (
    room_id TEXT NOT NULL,
    prop_instance_id TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json)),
    PRIMARY KEY (room_id, prop_instance_id),
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS room_owners (
    room_id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
PRAGMA user_version = 4;
COMMIT;
"""

_PROFILE_TABLES = frozenset({"accounts", "sessions", "profile_card_stacks", "world_profiles"})

_WORLD_TABLES = frozenset({"rooms", "room_cards", "prop_states", "room_owners"})

_ACCOUNTS_COLUMNS = (
    "id",
    "username_display",
    "username_key",
    "password_hash",
    "sticker",
    "initial_sticker_complete",
    "favorites_json",
    "level",
    "kudos",
    "bops",
    "shared_energy",
    "last_energy_at",
    "last_daily_claim",
    "friends_json",
    "pending_friends_json",
    "active_session_generation",
    "show_activity_log",
    "created_at",
    "updated_at",
)

_SESSIONS_COLUMNS = (
    "token_hash",
    "account_id",
    "csrf_token",
    "generation",
    "created_at",
    "expires_at",
    "last_seen_at",
)

_PROFILE_CARDS_COLUMNS = (
    "stack_id",
    "account_id",
    "world_id",
    "card_def_id",
    "quantity",
    "scope",
    "equipped",
    "pinned",
    "created_at",
    "updated_at",
)

_WORLD_PROFILES_COLUMNS = (
    "account_id",
    "world_id",
    "remembered_room",
    "native_cards_json",
    "counters_json",
    "buffs_json",
    "tasks_json",
    "memories_json",
    "ownership_json",
    "last_visit_at",
)

_ROOMS_COLUMNS = (
    "room_id",
    "seq",
    "revision",
    "chat_history_json",
)

_PROP_STATES_COLUMNS = (
    "room_id",
    "prop_instance_id",
    "state_json",
)

_ROOM_OWNERS_COLUMNS = (
    "room_id",
    "owner_account_id",
)

_ROOM_CARDS_COLUMNS = (
    "stack_id",
    "room_id",
    "card_def_id",
    "quantity",
    "pos_x",
    "pos_y",
    "pos_z",
    "scope",
    "pinned",
    "created_at",
    "updated_at",
)

def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _ensure_database(
    path: Path,
    *,
    expected_version: int,
    error_label: str,
    schema_sql: str,
    expected_tables: frozenset[str],
    column_specs: dict[str, tuple[str, ...]] | None = None,
    extra_indexes: tuple[str, ...] = (),
) -> None:
    """Create *path* when empty, else fail unless its schema matches exactly."""

    connection = _connect(path)
    try:
        version = _user_version(connection)
        if version == 0:
            connection.executescript(schema_sql)
            return
        if version != expected_version:
            raise RuntimeError(
                f"{error_label} database at {path} has schema version {version}, "
                f"expected {expected_version}. This server does not migrate databases: "
                "delete the file to recreate it (all data will be lost) "
                "or restore a compatible backup."
            )
        missing = sorted(expected_tables - _table_names(connection))
        if missing:
            raise RuntimeError(
                f"{error_label} database at {path} is incompatible: "
                f"missing tables {missing}. This server does not migrate databases: "
                "delete the file to recreate it (all data will be lost) "
                "or restore a compatible backup."
            )
        for table, expected_columns in (column_specs or {}).items():
            actual = _column_names(connection, table)
            if list(actual) != list(expected_columns):
                raise RuntimeError(
                    f"{error_label} database at {path} is incompatible: "
                    f'table "{table}" has columns {actual}, expected {list(expected_columns)}. '
                    "This server does not migrate databases: delete the file to "
                    "recreate it (all data will be lost) or restore a compatible backup."
                )
        for index_sql in extra_indexes:
            connection.execute(index_sql)
    finally:
        connection.close()


def ensure_profile_database(path: Path) -> None:
    """Create or validate the profile database schema, failing on mismatch."""

    _ensure_database(
        path,
        expected_version=PROFILE_SCHEMA_VERSION,
        error_label="Profile",
        schema_sql=_PROFILE_SCHEMA_SQL,
        expected_tables=_PROFILE_TABLES,
        column_specs={
            "accounts": _ACCOUNTS_COLUMNS,
            "sessions": _SESSIONS_COLUMNS,
            "profile_card_stacks": _PROFILE_CARDS_COLUMNS,
            "world_profiles": _WORLD_PROFILES_COLUMNS,
        },
        extra_indexes=(
            "CREATE INDEX IF NOT EXISTS idx_sessions_account_id ON sessions(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_profile_cards_owner ON profile_card_stacks(account_id, world_id)",
            "CREATE INDEX IF NOT EXISTS idx_profile_cards_lookup ON profile_card_stacks(account_id, card_def_id, scope)",
            "CREATE INDEX IF NOT EXISTS idx_world_profiles_world ON world_profiles(world_id)",
        ),
    )


def ensure_world_database(path: Path) -> None:
    """Create or validate the world-state database schema, failing on mismatch."""

    _ensure_database(
        path,
        expected_version=WORLD_SCHEMA_VERSION,
        error_label="World",
        schema_sql=_WORLD_SCHEMA_SQL,
        expected_tables=_WORLD_TABLES,
        column_specs={
            "rooms": _ROOMS_COLUMNS,
            "room_cards": _ROOM_CARDS_COLUMNS,
            "prop_states": _PROP_STATES_COLUMNS,
            "room_owners": _ROOM_OWNERS_COLUMNS,
        },
        extra_indexes=(
            "CREATE INDEX IF NOT EXISTS idx_room_cards_room_id ON room_cards(room_id)",
            "CREATE INDEX IF NOT EXISTS idx_room_cards_order ON room_cards(room_id, created_at, stack_id)",
        ),
    )


class DatabaseHub:
    """Shared attached SQLite connection used by runtime repositories."""

    def __init__(self, profile_path: Path, world_path: Path) -> None:
        self._connection = _connect(profile_path)
        self._connection.execute("ATTACH DATABASE ? AS world", (str(world_path),))
        self._connection.execute("PRAGMA world.journal_mode = WAL")
        self._lock = threading.RLock()

    @contextmanager
    def locked(self):
        """Yield the shared connection for a read-only critical section."""

        with self._lock:
            yield self._connection

    @contextmanager
    def transaction(self):
        """Yield the shared connection inside a BEGIN IMMEDIATE transaction."""

        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        """Close the shared runtime connection."""

        with self._lock:
            self._connection.close()
