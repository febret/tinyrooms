# Tinyrooms — Database Reference

This document records persistence ownership, operational guarantees, and
reserved-field intent. Exact DDL, columns, indexes, current schema versions,
and migration steps live in [migrations.py](../server/state/migrations.py)
(`_PROFILE_SCHEMA_SQL`, `_WORLD_SCHEMA_SQL`, version constants, migration maps,
and `ensure_*_database`). Repository/service links below replace parallel
column tables and CRUD descriptions.

## 1. Overview

| Database | Location | Ownership |
| --- | --- | --- |
| Profile | `<users_path>/profiles.sqlite3` | Accounts, sessions, inventory, per-user gameplay/profile state, idempotency logs, audit history |
| World | `TRSERVER_WORLDSTATE_PATH` (default `.local/worldstate.sqlite3`) | Shared live room content, ownership/layout, behavior/NPC state, world metadata, activity records |

At runtime [DatabaseHub](../server/state/migrations.py) opens the profile DB as
`main` and attaches the world DB as `world`. Both use WAL. Repository SQL
therefore qualifies world tables as `world.room_cards`, etc. Reads use the
shared lock; writes use `transaction()` (`BEGIN IMMEDIATE`, commit/rollback).
[Card transfers](../server/services/cards.py) and
[navigation](../server/services/rooms.py) use this connection to coordinate
profile and world changes in one application transaction.

Both databases also carry a same-shaped `vibes` table
(`world_id, source_peep_id, target_peep_id, value, updated_at`). Rows are
directed relationship scores clamped to -100..100; 0 is a retained neutral
score. Rows whose source is a player account live in the profile DB, while rows
whose source is an NPC live in the world DB. `world_id` keeps NPC targets and
player pairs scoped when one profile DB serves multiple worlds.
[VibesService](../server/services/vibes.py) owns the periodic stinky/charisma
rules, pair views, and descriptors; [VibesRepository](../server/state/vibes.py)
owns the SQL.

## 2. Profile (user) DB

### Identity, sessions, and inventory

[ProfileRepository](../server/profiles.py) owns `accounts`, `sessions`,
`profile_card_stacks`, and `user_profiles`; its records and normalization
functions define their runtime shapes. Authentication policy is in
[AccountService](../server/accounts.py), token/password handling in
[security.py](../server/security.py), and moderation/audit operations in
[PowersService](../server/services/powers.py).

Only the session token hash is stored; the plaintext token is in the HttpOnly
cookie. Session generation enforces one authoritative gameplay session.
Account progression fields are live gameplay state, not future placeholders;
sticker design and moderation fields are included in the current schema.

Inventory is physically in the profile DB even when a card is world-scoped.
Visible stacks are global (`world_id IS NULL`) plus the current world's stacks.
Card definitions determine scope/collectibility and stacking; see
[card loading](../server/content/cards.py) and
[CardService](../server/services/cards.py). `equipped` is implemented, not
reserved: equipped stacks are preferred merge targets, and pinned stacks are
excluded from merging/dropping by the repository.

### Unified user state and ownership

`user_profiles` has **one row per account**, not one per `(account, world)`.
Counters, buffs, ownership, and profile settings therefore share that row
across worlds. `last_world_id`, `remembered_room`, and `last_visit_at` track
resume/navigation; stable destination identity is
`profile_json.last_instance_id`. Entry repair and operator destination edits
rewrite only that key, preserving the saved world and room. See
[mission-control entry semantics](./mission-control.md) and the repository's
`remember_instance`, `reassign_last_instance`, and `ensure_user_profile` paths.

`profile_json` is extensible and normalized with defaults on read. Friends,
requests, pinned peeps, skill slots, statuses, UI settings, and unlocked props
are current consumers; do not treat all gameplay JSON as unused placeholders.

Room authority is world-local: `room_states.owner_account_id` is read by
[OwnershipService](../server/services/ownership.py). Its grant/revoke paths
update the `ownership_json.rooms` profile mirror in the same transaction.
Ownership grants and owner editing are implemented; the mirror is not a
replacement for world-side authorization.

### Idempotency scope

The profile DB holds these logs so their identity is **per account across
worlds**, not per world database:

- `reward_ledger`: `(ledger_key, account_id)`. A stable caller key makes the
  ledger check/insert, currency updates, and card grants one transaction in
  [ProgressionService](../server/services/progression.py). A duplicate returns
  false without a second grant. `world_id` records where the grant happened;
  it does **not** partition uniqueness. Callers must include any intended
  world/day distinction in the key. Grants without a key are not idempotent.
- `pack_purchases` and `pack_opens`: separate `(account_id, operation_id)`
  identities in [ShopService](../server/services/shop.py). Purchase charges
  Bops and grants a sealed pack once; open consumes a pack and grants its
  draw once. Draws are decided at **open**, not purchase. Replays do not charge
  or consume again; open results persist ordered card ids for replay.

Tasks use stable reward keys (`task:<id>`, or a day-qualified repeat key), and
[dialog choices](../server/services/dialogs.py) also use the reward ledger to
prevent repeated side effects. Idempotency protects these server mutations;
client presentation, including cutscenes, is never their completion signal.

### Tasks, memories, and reserved intent

[TaskService](../server/services/tasks.py) owns `task_progress`; rows are keyed
by account/task, with definition revision and repeat/reset policy governing
stale or repeatable progress. [MemoryService](../server/services/memories.py)
owns the journal view and owner-edited manual memories. Game memories are
immutable. Grouping and task game-day policy use the configured timezone.

Preserve these compatibility/future-intent distinctions:

- `native_cards_json`, `tasks_json`, and `memories_json` remain initialized
  compatibility/reserved blobs in the unified profile. Active task/journal
  storage is in `task_progress` and `memories`, not those placeholder blobs.
- `reward_ledger.payload_json` retains grant details for audit/replay intent.
  It is **not write-only**: MemoryService reads Kudos grants for monthly
  summaries. A general reward-replay/audit facility remains future work.
- `pack_purchases.results_json` remains reserved and is currently written as
  an empty list; it is not the drawn-card record. `pack_opens.results_json`
  is the implemented replay record.

## 3. World-state DB

[WorldStateRepository](../server/state/world_state.py) owns room cards,
initialization, layouts/environment, player-classroom records, and metadata.
[BehaviorDispatcher](../server/behaviors/dispatcher.py) persists trusted
script state through intent transactions; scripts do not access SQL directly.
[NPC state](../server/state/npc_peep_states.py) and
[activity records](../server/services/activity_results.py) have their own
access layers. Consult the schema for the complete current table set.

NPC location is implemented and overrides the authored spawn room once moved.
Its `counters_json`, `buffs_json`, and `memories_json` columns are reserved for
future per-NPC stats, buffs, and memories; they remain empty defaults today.

### Seed-once and reset loss

`room_states.initialized` is the restart-safety gate. On initialization, a
missing row or flag zero causes existing room cards to be deleted and YAML
seeds inserted; initialized rooms are left alone. Thus collected seeds stay
collected and player drops survive restarts. Templates are skipped until
materialized. Seed stack ids are deterministic; there is no separate seed
ledger or `initial_key` column in the live card table.

Changing YAML does not automatically replace initialized live cards/layouts.
Clearing the initialization flag causes reseeding on initialization and also
reseeds editable layout from the definition. Treat it as destructive state
replacement, not a harmless content-refresh flag.

`.reset_room` / `reset_room_cards()` replaces **all** live room stacks,
including player drops, with YAML seeds and marks the room initialized. This
card reset does not itself reset the editable layout. Preserve that loss
boundary when exposing reset tools.

Live room state includes owner, editable props, environment overrides, layout
revision, and classroom door settings. Layout saves use optimistic concurrency.
`classroom:` rooms reuse `room_states`; a partial unique index enforces one
classroom per account. See [room layouts](../server/services/room_layout.py)
and the repository rather than a duplicated JSON/column inventory.

### Durability boundaries

Room cards/layout/ownership, behavior state, NPC state, world metadata, and
activity records survive ordinary server restarts. Chat history is deliberately
process-local and bounded by the protocol history limit; it is lost on restart.
Broadcast ordering is in-process, with no persisted per-room sequence counter.

[Dispenser cooldowns](../server/services/dispensers.py) are process-local by
`(world_id, instance_id)`; dispensers restart ready. A legacy `prop_cooldowns`
table can remain in an upgraded DB but is unused. Cutscene playback/queues are
also transient, not room persistence.

## 4. Migration compatibility

Initialization creates fresh schemas or applies the available forward
migration chain, then validates required tables and exact expected column
lists and ensures indexes. Supported older DBs preserve state through these
migrations; “all migrations are additive” is too strong (for example NPC-state
migration copies then drops the old location table).

Newer schema versions are rejected rather than downgraded. A missing migration
step, missing table, or incompatible column layout also fails startup. A fresh
DB is **not** required only for newer versions: restore a compatible backup or
choose a fresh DB when no supported upgrade path exists. Use the version
constants and migration maps in [migrations.py](../server/state/migrations.py)
for compatibility decisions instead of stale version numbers in this document.
