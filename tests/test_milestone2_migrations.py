"""Milestone 2 migration tests: Milestone 1 databases stay loadable."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.state.migrations import (
    PROFILE_SCHEMA_VERSION,
    WORLD_SCHEMA_VERSION,
    ensure_profile_database,
    ensure_world_database,
)

_M1_PROFILE_SCHEMA = """
BEGIN;
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    username_display TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    sticker TEXT,
    initial_sticker_complete INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 0,
    kudos INTEGER NOT NULL DEFAULT 0,
    bops INTEGER NOT NULL DEFAULT 10,
    shared_energy INTEGER NOT NULL DEFAULT 80,
    last_energy_at TEXT NOT NULL,
    last_daily_claim TEXT,
    active_session_generation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    generation INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE profile_card_stacks (
    stack_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    world_id TEXT,
    card_def_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    scope TEXT NOT NULL,
    equipped INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE user_profiles (
    account_id TEXT PRIMARY KEY,
    last_world_id TEXT NOT NULL,
    remembered_room TEXT,
    native_cards_json TEXT NOT NULL,
    counters_json TEXT NOT NULL,
    buffs_json TEXT NOT NULL,
    tasks_json TEXT NOT NULL,
    memories_json TEXT NOT NULL,
    ownership_json TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    last_visit_at TEXT NOT NULL
);
PRAGMA user_version = 2;
COMMIT;
"""

_M1_WORLD_SCHEMA = """
BEGIN;
CREATE TABLE rooms (
    room_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    chat_history_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE room_cards (
    stack_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    card_def_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    position_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'room',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE prop_states (
    room_id TEXT NOT NULL,
    prop_instance_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (room_id, prop_instance_id)
);
CREATE TABLE room_owners (
    room_id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL
);
PRAGMA user_version = 5;
COMMIT;
"""


class MigrationTests(unittest.TestCase):
    """Existing Milestone 1 databases upgrade in place."""

    def test_profile_v2_migrates_to_v3_preserving_accounts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "profiles.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(_M1_PROFILE_SCHEMA)
            connection.execute(
                """
                INSERT INTO accounts (
                    id, username_display, username_key, password_hash, sticker,
                    initial_sticker_complete, level, kudos, bops, shared_energy,
                    last_energy_at, last_daily_claim, active_session_generation,
                    created_at, updated_at
                ) VALUES ('a1', 'Ada', 'ada', 'hash', 's1.png', 1, 3, 7, 42, 55,
                    '2024-01-01T00:00:00+00:00', NULL, 1,
                    '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')
                """
            )
            connection.commit()
            connection.close()

            ensure_profile_database(path)

            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], PROFILE_SCHEMA_VERSION)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("reward_ledger", tables)
            self.assertIn("pack_purchases", tables)
            row = connection.execute("SELECT level, kudos, bops FROM accounts WHERE id = 'a1'").fetchone()
            self.assertEqual(row, (3, 7, 42))
            connection.close()

    def test_legacy_world_database_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "worldstate.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(_M1_WORLD_SCHEMA)
            connection.commit()
            connection.close()
            with self.assertRaises(RuntimeError):
                ensure_world_database(path)


class Milestone3MigrationTests(unittest.TestCase):
    """Phase C/D additions upgrade the current schema versions in place."""

    def test_profile_v5_migrates_powers_and_audit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "profiles.sqlite3"
            ensure_profile_database(path)
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                BEGIN;
                DROP TABLE IF EXISTS audit_log;
                ALTER TABLE accounts DROP COLUMN powers;
                ALTER TABLE accounts DROP COLUMN muted_until;
                ALTER TABLE accounts DROP COLUMN muted_by;
                PRAGMA user_version = 5;
                COMMIT;
                """
            )
            connection.close()

            ensure_profile_database(path)

            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], PROFILE_SCHEMA_VERSION)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("audit_log", tables)
            self.assertNotIn("account_powers", tables)
            self.assertNotIn("moderation_state", tables)
            self.assertNotIn("craft_operations", tables)
            columns = [row[1] for row in connection.execute("PRAGMA table_info(accounts)")]
            self.assertIn("powers", columns)
            self.assertIn("muted_until", columns)
            self.assertIn("muted_by", columns)
            connection.close()

    def test_world_v7_migrates_to_environment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "worldstate.sqlite3"
            ensure_world_database(path)
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                BEGIN;
                ALTER TABLE room_states DROP COLUMN environment_json;
                ALTER TABLE room_states DROP COLUMN layout_revision;
                ALTER TABLE room_states DROP COLUMN door_json;
                PRAGMA user_version = 7;
                COMMIT;
                """
            )
            connection.close()

            ensure_world_database(path)

            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], WORLD_SCHEMA_VERSION)
            columns = [row[1] for row in connection.execute("PRAGMA table_info(room_states)")]
            self.assertIn("environment_json", columns)
            self.assertIn("layout_revision", columns)
            self.assertIn("door_json", columns)
            connection.close()


if __name__ == "__main__":
    unittest.main()
