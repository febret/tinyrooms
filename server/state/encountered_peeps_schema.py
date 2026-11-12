"""Encountered-peep sticker collection schema: shared profile table and v16 migration."""

from __future__ import annotations


ENCOUNTERED_PEEPS_COLUMNS = (
    "account_id",
    "peep_key",
    "world_id",
    "peep_id",
    "label",
    "description",
    "image_name",
    "vibe",
    "traits_json",
    "counts_toward_rewards",
    "first_room_id",
    "first_met_at",
    "last_met_at",
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS encountered_peeps (
    account_id TEXT NOT NULL,
    -- <world_id>:<peep_id>, globally unique across every world process.
    peep_key TEXT NOT NULL,
    world_id TEXT NOT NULL,
    peep_id TEXT NOT NULL,
    -- Label, description, and picture are snapshotted at first encounter so the
    -- sticker survives world edits. image_name lives under custom stickers/peeps.
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image_name TEXT NOT NULL DEFAULT '',
    -- Latest observed peep-to-player vibe, refreshed on each encounter.
    vibe INTEGER NOT NULL DEFAULT 0,
    traits_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(traits_json)),
    -- Mod-generated peeps are collected but do not advance reward milestones.
    counts_toward_rewards INTEGER NOT NULL DEFAULT 1 CHECK (counts_toward_rewards IN (0, 1)),
    first_room_id TEXT NOT NULL DEFAULT '',
    first_met_at TEXT NOT NULL,
    last_met_at TEXT NOT NULL,
    PRIMARY KEY (account_id, peep_key),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_encountered_peeps_owner ON encountered_peeps(account_id, first_met_at);
"""

ENCOUNTERED_PEEPS_FRESH_SQL = _TABLE_SQL

ENCOUNTERED_PEEPS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_encountered_peeps_owner ON encountered_peeps(account_id, first_met_at)",
)

ENCOUNTERED_PEEPS_MIGRATION = (
    "BEGIN;\n" + _TABLE_SQL + "PRAGMA user_version = 16;\nCOMMIT;\n"
)
