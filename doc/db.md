# Tinyrooms — Database Reference

This document describes the SQLite schemas for the two databases used by the
Milestone 1 backend. The schema source of truth is
`server/state/migrations.py`; the runtime access layer is
`server/profiles.py` (profile DB) and `server/state/world_state.py` (world DB).

## 1. Overview

| Database | File | Schema version | Initialization entrypoint |
| --- | --- | --- | --- |
| Profile (user) DB | `<users_path>/profiles.sqlite3` | 1 (`PROFILE_SCHEMA_VERSION`) | `ensure_profile_database()` |
| World-state DB | `TRSERVER_WORLDSTATE_PATH` (default `.local/worldstate.sqlite3`) | 4 (`WORLD_SCHEMA_VERSION`) | `ensure_world_database()` |

There are no automatic migrations. `ensure_*` creates a missing (or
zero-version) database from the current schema, then fails startup with a
`RuntimeError` when an existing file has any other `user_version`, is missing
expected tables, or has unexpected columns (every table's column order is
validated). World-state schema versions 1–3 (which carried
`room_cards.initial_key` and/or the `initial_room_cards` ledger) are therefore
rejected: delete the stale file to recreate it or restore a compatible
backup. `ensure_*` also applies
`CREATE INDEX IF NOT EXISTS` for all indexes listed below, so pre-existing
databases gain the newer indexes without a version bump. `CHECK` constraints
(`quantity > 0`, boolean `IN (0, 1)`, `json_valid()` on JSON columns,
non-negative counters/sequences) are enforced on newly created databases;
older files keep relying on the matching Python-side validation.

At runtime both files are accessed through a single shared connection,
`server/state/migrations.py:DatabaseHub`, which opens the profile DB and
`ATTACH`es the world DB as `world`. Both databases run in WAL mode
(`PRAGMA journal_mode = WAL` on `main` plus `PRAGMA world.journal_mode = WAL`
after attach). All repository SQL therefore addresses
world tables as `world.rooms`, `world.room_cards`, and so on. `DatabaseHub`
exposes `locked()` for reads and `transaction()` (`BEGIN IMMEDIATE`, commit or
rollback) for writes; multi-table mutations such as pickup/drop
(`server/services/cards.py`) and navigation (`server/services/rooms.py`) run
inside one transaction spanning both databases.

## 2. Profile (user) DB — `<users_path>/profiles.sqlite3`

### 2.1 `accounts`

One row per registered user. Created by
`server/profiles.py:ProfileRepository.create_account()` (called from
`server/accounts.py:AccountService.create_account()`); read by
`get_account_by_id()` / `get_account_by_username()` / `get_accounts_by_ids()`
(single-query batch used for room occupants); mutated by `set_sticker()`,
`toggle_favorite()`, `set_show_activity_log()`, and `issue_session()` (bumps
`active_session_generation`). Serialized to the client in
`server/app.py:_serialize_account()`.

| Column | Type | Description |
| --- | --- | --- |
| `id` | TEXT PK | Account UUID (`uuid4`). Referenced by `sessions`, `profile_card_stacks`, `world_profiles`. |
| `username_display` | TEXT NOT NULL | Username with original casing, shown in UI/presence. |
| `username_key` | TEXT NOT NULL UNIQUE | Casefolded username for uniqueness/login lookup (`normalize_username()`). |
| `password_hash` | TEXT NOT NULL | scrypt hash (`scrypt$n$r$p$salt$digest`), see `server/security.py:hash_password()` / `verify_password()`. |
| `sticker` | TEXT NULL | Chosen sticker filename under `data/stickers`; NULL until confirmed. Set once by `set_sticker()`. |
| `initial_sticker_complete` | INTEGER NOT NULL DEFAULT 0 | Boolean. Gates world entry (`/ws` closes `4403` until true). |
| `favorites_json` | TEXT NOT NULL | JSON list of core-card IDs favorited via `.favorite` (`toggle_favorite()`). |
| `level` | INTEGER NOT NULL DEFAULT 0 | Progression level (Milestone 1: always 0 for new users; future use per `data/core/levels.yaml`). |
| `kudos` | INTEGER NOT NULL DEFAULT 0 | Kudos balance (future level-up currency). |
| `bops` | INTEGER NOT NULL DEFAULT 10 | Bops balance (future spendable currency). |
| `shared_energy` | INTEGER NOT NULL DEFAULT 80 | Shared energy pool (future juice system, cf. `data/core/juice.yaml`). |
| `last_energy_at` | TEXT NOT NULL | ISO timestamp of last energy update/recharge baseline. |
| `last_daily_claim` | TEXT NULL | ISO timestamp/date of last daily Bops claim; NULL if never claimed. |
| `friends_json` | TEXT NOT NULL | JSON list of friend account IDs/usernames (Milestone 1: `[]`). |
| `pending_friends_json` | TEXT NOT NULL | JSON list of pending friend requests (Milestone 1: `[]`). |
| `active_session_generation` | INTEGER NOT NULL DEFAULT 0 | Incremented on every `issue_session()`; enforces one live gameplay session (old sockets get `session.replaced`). |
| `show_activity_log` | INTEGER NOT NULL DEFAULT 0 | Boolean. Action Log visibility, toggled by `.settings action-log` (`set_show_activity_log()`). |
| `created_at` | TEXT NOT NULL | ISO creation timestamp. |
| `updated_at` | TEXT NOT NULL | ISO last-update timestamp (bumped on sticker/favorite/settings/session changes). |

### 2.2 `sessions`

Server-side login sessions. Written by
`server/profiles.py:issue_session()` (deletes all prior rows for the account,
bumps `active_session_generation`, inserts one row), read by
`get_session_by_token()`, refreshed by `touch_session()`, deleted by
`revoke_session()`. Session/auth orchestration is in
`server/accounts.py:AccountService` (`login`, `authenticate`, `logout`);
expiry is checked there against `expires_at`. Only the SHA-256 hash of the
opaque token is stored (`server/security.py:hash_session_token()`); the
plaintext token lives in the `tr_session` HttpOnly cookie.

| Column | Type | Description |
| --- | --- | --- |
| `token_hash` | TEXT PK | SHA-256 hex of the opaque session token (`SESSION_TOKEN_BYTES = 32`). Lookup key. |
| `account_id` | TEXT NOT NULL FK → `accounts(id)` ON DELETE CASCADE | Owning account. Indexed via `idx_sessions_account_id`. |
| `csrf_token` | TEXT NOT NULL | Per-session CSRF token, mirrored in the `tr_csrf` cookie and `X-CSRF-Token` header. |
| `generation` | INTEGER NOT NULL | Copy of `accounts.active_session_generation` at issue time; stale generations lose WS authority. |
| `created_at` | TEXT NOT NULL | ISO issue timestamp. |
| `expires_at` | TEXT NOT NULL | ISO expiry (`utc_now() + 14 days`, `DEFAULT_SESSION_DAYS`). |
| `last_seen_at` | TEXT NOT NULL | ISO last-activity timestamp, refreshed by `touch_session()` at most once per `SESSION_TOUCH_INTERVAL_SECONDS` (60s) to avoid a write transaction on every request. |

### 2.3 `profile_card_stacks`

Per-account inventory card stacks. Listed/filtered by `list_inventory()` and
`get_inventory_stack()` (visible stacks are `world_id IS NULL OR world_id = ?`);
mutated atomically inside card transactions by `add_inventory_card()` /
`remove_inventory_quantity()`, called from `server/services/cards.py:pickup()`
and `drop()`. Serialized via `CardService.serialize_inventory_stack()`.

Starter rows (`stack_id = 'global:<account_id>:<card_id>'`) are seeded at
account creation; picked-up cards get `stack_id = 'inv:<uuid4>'` and are merged
up to the definition `stack_limit`. `add_inventory_card()` /
`remove_inventory_quantity()` build their return values in Python instead of
re-selecting each touched row; `pickup()` / `drop()` still re-list the full
inventory once for the client payload. Besides `idx_profile_cards_owner`,
`idx_profile_cards_lookup (account_id, card_def_id, scope)` covers the
pickup-merge filter and the `.go` card-requirement scan.

| Column | Type | Description |
| --- | --- | --- |
| `stack_id` | TEXT PK | Stack identifier (`global:<account>:<card>` for starters, `inv:<uuid>` otherwise). Referenced by `.drop @card:<stack_id>` and `.look @card:<stack_id>`. |
| `account_id` | TEXT NOT NULL FK → `accounts(id)` ON DELETE CASCADE | Owning account. Indexed via `idx_profile_cards_owner`. |
| `world_id` | TEXT NULL | `NULL` for global (cross-world) cards, otherwise the world the collectible belongs to. Part of `idx_profile_cards_owner`. |
| `card_def_id` | TEXT NOT NULL | Card definition ID from the catalog (`server/content/cards.py`). |
| `quantity` | INTEGER NOT NULL | Cards in this stack; merges/splits respect the definition `stack_limit`. |
| `scope` | TEXT NOT NULL | `'global'` (non-collectible, e.g. starters) or `'world'` (collectible). |
| `equipped` | INTEGER NOT NULL DEFAULT 0 | Boolean. Reserved: equipped stacks are excluded from pickup-merge targets (future skill slots). |
| `pinned` | INTEGER NOT NULL DEFAULT 0 | Boolean. Pinned stacks cannot be dropped (`remove_inventory_quantity()` rejects). |
| `created_at` | TEXT NOT NULL | ISO creation timestamp; determines merge/fill and list ordering. |
| `updated_at` | TEXT NOT NULL | ISO last-quantity-change timestamp. |

### 2.4 `world_profiles`

One row per (account, world). Created by `create_account()` and lazily by
`ensure_world_profile()`; read by `get_world_profile()` and
`RoomService.current_room_for_account()`; `remembered_room`/`last_visit_at`
updated by `set_remembered_room()` on every `.go` (`server/services/rooms.py`)
and used for resume on WS connect and `/api/bootstrap`
(`server/app.py:_serialize_account()`). The `*_json` gameplay blobs are
Milestone 1 placeholders (defaults below) reserved for later milestones.

| Column | Type | Description |
| --- | --- | --- |
| `account_id` | TEXT NOT NULL, PK part 1, FK → `accounts(id)` ON DELETE CASCADE | Owning account. |
| `world_id` | TEXT NOT NULL, PK part 2 | World ID (e.g. tutorial world). Composite PK `(account_id, world_id)`; `idx_world_profiles_world (world_id)` covers per-world scans. |
| `remembered_room` | TEXT NULL | Last room the user occupied; WS connect resumes here if still in the world, else falls back to the entry room. |
| `native_cards_json` | TEXT NOT NULL | JSON dict of world-native card state (Milestone 1: `'{}'`). |
| `counters_json` | TEXT NOT NULL | JSON dict of world counters; seeded with `STARTING_WORLD_COUNTERS` (health/max_health, cleanliness/max_cleanliness, constitution, dexterity, charisma, fanciness). |
| `buffs_json` | TEXT NOT NULL | JSON dict of active buffs (Milestone 1: `'{}'`). |
| `tasks_json` | TEXT NOT NULL | JSON dict of quest/task state (Milestone 1: `'{}'`). |
| `memories_json` | TEXT NOT NULL | JSON dict of memory flags (Milestone 1: `'{}'`). |
| `ownership_json` | TEXT NOT NULL | JSON dict of ownership claims (Milestone 1: `'{}'`). |
| `last_visit_at` | TEXT NOT NULL | ISO timestamp of last room change; updated together with `remembered_room`. |

## 3. World-state DB — `TRSERVER_WORLDSTATE_PATH`

### 3.1 `rooms`

One row per room in the loaded world definition. Ensured by
`server/state/world_state.py:WorldStateRepository.initialize_world()`, which
creates a row plus its seed cards only when the room is absent; rooms already
present are left untouched, so YAML edits to an existing room's cards never
re-seed implicitly (use `.reset_room` instead). `seq` is the authoritative per-room
broadcast counter: every chat, pickup/drop, presence move, and navigation
advances it via `advance_room_seq()` / `append_chat_message()` and the
resulting `seq` is sent in `room.snapshot` / `room.event` envelopes
(`server/protocol.py`, `server/app.py` WS loop). Snapshots are built by
`RoomService.build_snapshot_with_seq()`, which reads occupants (one batched
`get_accounts_by_ids()` query instead of N+1 lookups), room cards, chat
history, sequence, and inventory under a single `DatabaseHub.locked()` hold so
the snapshot cannot tear across concurrent writes; it returns the snapshot
together with the sequence it is consistent with. `chat_history_json` is read by
`get_chat_history()` / `read_room_view()` and included in snapshots.

| Column | Type | Description |
| --- | --- | --- |
| `room_id` | TEXT PK | Room ID from `worlds/<world>/rooms/*.yaml` (Milestone 1 playable: `hub`, `playroom`). |
| `seq` | INTEGER NOT NULL DEFAULT 0 | Monotonic per-room sequence for ordering broadcasts; clients re-request a snapshot on gap. |
| `revision` | INTEGER NOT NULL DEFAULT 0 | Reserved revision counter for future definition/layout edits; always 0 in Milestone 1. |
| `chat_history_json` | TEXT NOT NULL DEFAULT `'[]'` | JSON list of recent `{speaker_id, speaker, style, text}` entries; appended by `RoomService.say()` via `append_chat_message()` and capped at `MAX_HISTORY_MESSAGES` (50). |

### 3.2 `room_cards`

Live card stacks lying in rooms. Seeded from `room.initial_cards` by
`initialize_world()` when the room row is first created; listed by
`list_room_cards()` for snapshots; mutated by `take_room_card()` (pickup) and
`add_room_card()` (drop) inside `CardService` transactions, each advancing the
room `seq` and broadcasting `room.card.added/updated/removed`
(`server/services/cards.py`, `server/commands/core.py`). `.reset_room`
(`reset_room_cards()`) deletes every live stack in the caller's room —
including player drops — re-inserts the YAML seeds, advances `seq`, and
broadcasts `room.cards.reset`.

| Column | Type | Description |
| --- | --- | --- |
| `stack_id` | TEXT PK | Stack ID: `room:<seed key>` for seeded stacks, `room:<uuid4>` for dropped cards. Referenced by `.pickup @card:<stack_id>` and `.look @card:<stack_id>`. |
| `room_id` | TEXT NOT NULL FK → `rooms(room_id)` ON DELETE CASCADE | Containing room. Indexed via `idx_room_cards_room_id` and `idx_room_cards_order (room_id, created_at, stack_id)`, which covers the snapshot `ORDER BY`. |
| `card_def_id` | TEXT NOT NULL | Card definition ID from the catalog. |
| `quantity` | INTEGER NOT NULL | Cards in this stack. |
| `pos_x` / `pos_y` / `pos_z` | REAL NOT NULL | Board position triple; seeded from YAML `pos`, drops land at `(50, 50, 0)` (`core.py`). |
| `scope` | TEXT NOT NULL DEFAULT `'room'` | Always `'room'` in Milestone 1; mirrors the inventory `scope` vocabulary. |
| `pinned` | INTEGER NOT NULL DEFAULT 0 | Boolean. Pinned stacks reject `.pickup` (`take_room_card()`). |
| `created_at` | TEXT NOT NULL | ISO creation timestamp; list ordering key. |
| `updated_at` | TEXT NOT NULL | ISO last-quantity-change timestamp. |

Seeded stacks use a deterministic `stack_id` (`room:<seed key>`, where the
seed key is `<room>:<index>:<card>` from the content loader in
`server/content/worlds.py`); `room_cards` carries no `initial_key` column and
there is no seed ledger table. Restart safety comes from the room-exists gate
in `initialize_world()`: existing rooms are never re-seeded, so collected
seeds stay collected and dropped cards stay dropped.

### 3.3 `prop_states`

Placeholder for future dynamic prop state (Milestone 1 renders props purely
from YAML in `RoomService._serialize_prop()`; no code reads or writes this
table yet). Schema is created alongside the other world
tables per `doc/milestone-1.md` §4 ("prop state placeholders").

| Column | Type | Description |
| --- | --- | --- |
| `room_id` | TEXT NOT NULL, PK part 1, FK → `rooms(room_id)` ON DELETE CASCADE | Room containing the prop instance. |
| `prop_instance_id` | TEXT NOT NULL, PK part 2 | Prop instance ID within the room. Composite PK `(room_id, prop_instance_id)`. |
| `state_json` | TEXT NOT NULL | JSON blob of dynamic prop state (unused in Milestone 1). |

### 3.4 `room_owners`

Placeholder for future room ownership (no code reads or writes this table in
Milestone 1). Schema is created alongside the other world tables per
`doc/milestone-1.md` §4 ("room ownership").

| Column | Type | Description |
| --- | --- | --- |
| `room_id` | TEXT PK, FK → `rooms(room_id)` ON DELETE CASCADE | Owned room. |
| `owner_account_id` | TEXT NOT NULL | Owning `accounts.id`. |

### 3.5 Seed updates (no ledger table)

There is intentionally no `initial_room_cards` ledger: `initialize_world()`
seeds a room exactly once, at creation. Consequences:

- Restarts never duplicate or respawn room cards.
- Adding or editing YAML cards for an *existing* room has no effect until the
  room is explicitly reset; adding a *new* room seeds it on next startup.
- `.reset_room` is the explicit content-update path: it replaces the room's
  live cards with the current YAML seeds (see §3.2).
