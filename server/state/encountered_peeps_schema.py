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
    "tags_json",
    "traits_json",
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
    -- Vibes are not stored here; they are read live from the global vibes table.
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image_name TEXT NOT NULL DEFAULT '',
    -- Peep tags (e.g. trait:<id>), refreshed on every encounter.
    tags_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags_json)),
    traits_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(traits_json)),
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

# Early v16 builds created encountered_peeps with vibe/counts_toward_rewards and
# no tags_json. Rebuild unconditionally from the columns both shapes share; tags
# start empty and refresh on the next encounter.
_SHARED_COLUMNS = (
    "account_id, peep_key, world_id, peep_id, label, description, image_name,"
    " traits_json, first_room_id, first_met_at, last_met_at"
)

ENCOUNTERED_PEEPS_REBUILD_MIGRATION = (
    "BEGIN;\n"
    "ALTER TABLE encountered_peeps RENAME TO encountered_peeps_legacy;\n"
    "DROP INDEX IF EXISTS idx_encountered_peeps_owner;\n"
    + _TABLE_SQL
    + f"INSERT INTO encountered_peeps ({_SHARED_COLUMNS})\n"
    f"    SELECT {_SHARED_COLUMNS} FROM encountered_peeps_legacy\n"
    "    WHERE account_id IN (SELECT id FROM accounts);\n"
    "DROP TABLE encountered_peeps_legacy;\n"
    "PRAGMA user_version = 18;\n"
    "COMMIT;\n"
)
