"""SQLite schema migrations for profile and world-state databases."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading


PROFILE_SCHEMA_VERSION = 1
WORLD_SCHEMA_VERSION = 2


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _migrate(path: Path, *, target_version: int, error_label: str, steps: dict[int, str]) -> None:
    """Bring the database at ``path`` up to ``target_version`` by running any pending ``steps`` in order."""

    connection = _connect(path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > target_version:
            raise RuntimeError(f"{error_label} database is newer than this server supports.")
        for step_version in sorted(steps):
            if version < step_version:
                connection.executescript(steps[step_version])
    finally:
        connection.close()


def migrate_profile_database(path: Path) -> None:
    """Create or upgrade the profile database schema."""

    _migrate(
        path,
        target_version=PROFILE_SCHEMA_VERSION,
        error_label="Profile",
        steps={
            1: """
                BEGIN;
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    username_display TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    sticker TEXT,
                    initial_sticker_complete INTEGER NOT NULL DEFAULT 0,
                    favorites_json TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    kudos INTEGER NOT NULL DEFAULT 0,
                    bops INTEGER NOT NULL DEFAULT 10,
                    shared_energy INTEGER NOT NULL DEFAULT 80,
                    last_energy_at TEXT NOT NULL,
                    last_daily_claim TEXT,
                    friends_json TEXT NOT NULL,
                    pending_friends_json TEXT NOT NULL,
                    active_session_generation INTEGER NOT NULL DEFAULT 0,
                    show_activity_log INTEGER NOT NULL DEFAULT 0,
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
                    quantity INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    equipped INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_profile_cards_owner ON profile_card_stacks(account_id, world_id);
                CREATE TABLE IF NOT EXISTS world_profiles (
                    account_id TEXT NOT NULL,
                    world_id TEXT NOT NULL,
                    remembered_room TEXT,
                    native_cards_json TEXT NOT NULL,
                    counters_json TEXT NOT NULL,
                    buffs_json TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    memories_json TEXT NOT NULL,
                    ownership_json TEXT NOT NULL,
                    last_visit_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, world_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                );
                PRAGMA user_version = 1;
                COMMIT;
                """,
        },
    )


def migrate_world_database(path: Path) -> None:
    """Create or upgrade the world-state database schema."""

    _migrate(
        path,
        target_version=WORLD_SCHEMA_VERSION,
        error_label="World",
        steps={
            1: """
                BEGIN;
                CREATE TABLE IF NOT EXISTS rooms (
                    room_id TEXT PRIMARY KEY,
                    seq INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0,
                    chat_history_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS room_cards (
                    stack_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    card_def_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    pos_x REAL NOT NULL,
                    pos_y REAL NOT NULL,
                    pos_z REAL NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'room',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    initial_key TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_room_cards_room_id ON room_cards(room_id);
                CREATE TABLE IF NOT EXISTS prop_states (
                    room_id TEXT NOT NULL,
                    prop_instance_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    PRIMARY KEY (room_id, prop_instance_id),
                    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS room_owners (
                    room_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
                );
                PRAGMA user_version = 1;
                COMMIT;
                """,
            2: """
                BEGIN;
                CREATE TABLE IF NOT EXISTS initial_room_cards (
                    initial_key TEXT PRIMARY KEY,
                    seeded_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO initial_room_cards (initial_key, seeded_at)
                SELECT initial_key, created_at
                FROM room_cards
                WHERE initial_key IS NOT NULL;
                PRAGMA user_version = 2;
                COMMIT;
                """,
        },
    )


class DatabaseHub:
    """Shared attached SQLite connection used by runtime repositories."""

    def __init__(self, profile_path: Path, world_path: Path) -> None:
        self._connection = _connect(profile_path)
        self._connection.execute("ATTACH DATABASE ? AS world", (str(world_path),))
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
