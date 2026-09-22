"""SQLite schema initialization and validation for profile and world-state databases."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading


PROFILE_SCHEMA_VERSION = 3
WORLD_SCHEMA_VERSION = 6

_PROFILE_SCHEMA_SQL = """
BEGIN;
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username_display TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    sticker TEXT,
    initial_sticker_complete INTEGER NOT NULL DEFAULT 0 CHECK (initial_sticker_complete IN (0, 1)),
    level INTEGER NOT NULL DEFAULT 0 CHECK (level >= 0),
    kudos INTEGER NOT NULL DEFAULT 0 CHECK (kudos >= 0),
    bops INTEGER NOT NULL DEFAULT 10 CHECK (bops >= 0),
    shared_energy INTEGER NOT NULL DEFAULT 80 CHECK (shared_energy >= 0),
    last_energy_at TEXT NOT NULL,
    last_daily_claim TEXT,
    active_session_generation INTEGER NOT NULL DEFAULT 0 CHECK (active_session_generation >= 0),
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
CREATE TABLE IF NOT EXISTS user_profiles (
    account_id TEXT PRIMARY KEY,
    last_world_id TEXT NOT NULL,
    remembered_room TEXT,
    native_cards_json TEXT NOT NULL CHECK (json_valid(native_cards_json)),
    counters_json TEXT NOT NULL CHECK (json_valid(counters_json)),
    buffs_json TEXT NOT NULL CHECK (json_valid(buffs_json)),
    tasks_json TEXT NOT NULL CHECK (json_valid(tasks_json)),
    memories_json TEXT NOT NULL CHECK (json_valid(memories_json)),
    ownership_json TEXT NOT NULL CHECK (json_valid(ownership_json)),
    profile_json TEXT NOT NULL CHECK (json_valid(profile_json)),
    last_visit_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reward_ledger (
    ledger_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (ledger_key, account_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reward_ledger_owner ON reward_ledger(account_id, world_id);
CREATE TABLE IF NOT EXISTS pack_purchases (
    operation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    results_json TEXT NOT NULL CHECK (json_valid(results_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pack_purchases_owner ON pack_purchases(account_id);
PRAGMA user_version = 3;
COMMIT;
"""

_WORLD_SCHEMA_SQL = """
BEGIN;
CREATE TABLE IF NOT EXISTS room_cards (
    stack_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    card_def_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    position_json TEXT NOT NULL CHECK (json_valid(position_json)),
    scope TEXT NOT NULL DEFAULT 'room',
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_room_cards_room_id ON room_cards(room_id);
CREATE INDEX IF NOT EXISTS idx_room_cards_order ON room_cards(room_id, created_at, stack_id);
CREATE TABLE IF NOT EXISTS room_states (
    room_id TEXT PRIMARY KEY,
    initialized INTEGER NOT NULL DEFAULT 0 CHECK (initialized IN (0, 1)),
    owner_account_id TEXT,
    props_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(props_json))
);
PRAGMA user_version = 6;
COMMIT;
"""

_PROFILE_TABLES = frozenset(
    {"accounts", "sessions", "profile_card_stacks", "user_profiles", "reward_ledger", "pack_purchases"}
)

_WORLD_TABLES = frozenset({"room_cards", "room_states"})

_PROFILE_MIGRATIONS: dict[int, str] = {
    3: """
    BEGIN;
    CREATE TABLE IF NOT EXISTS reward_ledger (
        ledger_key TEXT NOT NULL,
        account_id TEXT NOT NULL,
        world_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        created_at TEXT NOT NULL,
        PRIMARY KEY (ledger_key, account_id),
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_reward_ledger_owner ON reward_ledger(account_id, world_id);
    CREATE TABLE IF NOT EXISTS pack_purchases (
        operation_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        pack_id TEXT NOT NULL,
        results_json TEXT NOT NULL CHECK (json_valid(results_json)),
        created_at TEXT NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_pack_purchases_owner ON pack_purchases(account_id);
    PRAGMA user_version = 3;
    COMMIT;
    """,
}

_REWARD_LEDGER_COLUMNS = (
    "ledger_key",
    "account_id",
    "world_id",
    "kind",
    "payload_json",
    "created_at",
)

_PACK_PURCHASES_COLUMNS = (
    "operation_id",
    "account_id",
    "pack_id",
    "results_json",
    "created_at",
)

_ACCOUNTS_COLUMNS = (
    "id",
    "username_display",
    "username_key",
    "password_hash",
    "sticker",
    "initial_sticker_complete",
    "level",
    "kudos",
    "bops",
    "shared_energy",
    "last_energy_at",
    "last_daily_claim",
    "active_session_generation",
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

_USER_PROFILES_COLUMNS = (
    "account_id",
    "last_world_id",
    "remembered_room",
    "native_cards_json",
    "counters_json",
    "buffs_json",
    "tasks_json",
    "memories_json",
    "ownership_json",
    "profile_json",
    "last_visit_at",
)

_ROOM_STATES_COLUMNS = (
    "room_id",
    "initialized",
    "owner_account_id",
    "props_json",
)

_ROOM_CARDS_COLUMNS = (
    "stack_id",
    "room_id",
    "card_def_id",
    "quantity",
    "position_json",
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
    migrations: dict[int, str] | None = None,
) -> None:
    """Create *path* when empty, migrate forward, or fail on an unknown version.

    Existing databases at a supported older version are upgraded in place with
    additive migrations so accounts and world state survive Milestone upgrades.
    Databases newer than this build are rejected rather than downgraded.
    """

    connection = _connect(path)
    try:
        version = _user_version(connection)
        if version == 0:
            connection.executescript(schema_sql)
            return
        if version > expected_version:
            raise RuntimeError(
                f"{error_label} database at {path} has schema version {version}, "
                f"newer than this build supports ({expected_version}). "
                "Restore a matching backup or start this build against a fresh database."
            )
        steps = migrations or {}
        while version < expected_version:
            next_version = version + 1
            script = steps.get(next_version)
            if script is None:
                raise RuntimeError(
                    f"{error_label} database at {path} has schema version {version} but no "
                    f"migration to {next_version} is available. Restore a compatible backup "
                    "or start this build against a fresh database."
                )
            connection.executescript(script)
            version = _user_version(connection)
        missing = sorted(expected_tables - _table_names(connection))
        if missing:
            raise RuntimeError(
                f"{error_label} database at {path} is incompatible: "
                f"missing tables {missing}. Restore a compatible backup or start this "
                "build against a fresh database."
            )
        for table, expected_columns in (column_specs or {}).items():
            actual = _column_names(connection, table)
            if list(actual) != list(expected_columns):
                raise RuntimeError(
                    f"{error_label} database at {path} is incompatible: "
                    f'table "{table}" has columns {actual}, expected {list(expected_columns)}. '
                    "Restore a compatible backup or start this build against a fresh database."
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
            "user_profiles": _USER_PROFILES_COLUMNS,
            "reward_ledger": _REWARD_LEDGER_COLUMNS,
            "pack_purchases": _PACK_PURCHASES_COLUMNS,
        },
        extra_indexes=(
            "CREATE INDEX IF NOT EXISTS idx_sessions_account_id ON sessions(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_profile_cards_owner ON profile_card_stacks(account_id, world_id)",
            "CREATE INDEX IF NOT EXISTS idx_profile_cards_lookup ON profile_card_stacks(account_id, card_def_id, scope)",
            "CREATE INDEX IF NOT EXISTS idx_reward_ledger_owner ON reward_ledger(account_id, world_id)",
            "CREATE INDEX IF NOT EXISTS idx_pack_purchases_owner ON pack_purchases(account_id)",
        ),
        migrations=_PROFILE_MIGRATIONS,
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
            "room_cards": _ROOM_CARDS_COLUMNS,
            "room_states": _ROOM_STATES_COLUMNS,
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
