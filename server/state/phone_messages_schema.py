"""Phone message inbox schema: shared profile table, thread keys, and v13 migration."""

from __future__ import annotations


PHONE_MESSAGES_COLUMNS = (
    "message_id",
    "owner_account_id",
    "thread_key",
    "direction",
    "sender_name",
    "body",
    "created_at",
    "read_at",
    "world_id",
    "meta_json",
)

PHONE_MESSAGES_FRESH_SQL = """
CREATE TABLE IF NOT EXISTS phone_messages (
    -- One row per phone copy: a friend send writes two rows (outbox + inbox),
    -- while NPC and system messages write a single inbox row for the owner.
    message_id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL,
    -- player:<account_id>, npc:<world_id>:<npc_id>, or system:<source_id>.
    thread_key TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    -- Display name captured at write time, not a live account lookup.
    sender_name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- NULL until the owning phone opens the thread.
    read_at TEXT,
    -- Provenance only; threads are never partitioned by world.
    world_id TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(meta_json)),
    FOREIGN KEY (owner_account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_phone_messages_owner ON phone_messages(owner_account_id, thread_key, created_at);
CREATE INDEX IF NOT EXISTS idx_phone_messages_unread ON phone_messages(owner_account_id, read_at);
"""

PHONE_MESSAGES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_phone_messages_owner ON phone_messages(owner_account_id, thread_key, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_phone_messages_unread ON phone_messages(owner_account_id, read_at)",
)

PHONE_MESSAGES_MIGRATION = """
BEGIN;
CREATE TABLE IF NOT EXISTS phone_messages (
    message_id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    sender_name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    world_id TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(meta_json)),
    FOREIGN KEY (owner_account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_phone_messages_owner ON phone_messages(owner_account_id, thread_key, created_at);
CREATE INDEX IF NOT EXISTS idx_phone_messages_unread ON phone_messages(owner_account_id, read_at);
PRAGMA user_version = 13;
COMMIT;
"""
