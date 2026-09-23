# Tinyrooms — Database Reference

This document describes the SQLite schemas for the two databases used by the
Milestone 2 backend. The schema source of truth is
`server/state/migrations.py`; the runtime access layer is
`server/profiles.py` (profile DB) and `server/state/world_state.py` (world DB).

## 1. Overview

| Database | File | Schema version | Initialization entrypoint |
| --- | --- | --- | --- |
| Profile (user) DB | `<users_path>/profiles.sqlite3` | 8 (`PROFILE_SCHEMA_VERSION`) | `ensure_profile_database()` |
| World-state DB | `TRSERVER_WORLDSTATE_PATH` (default `.local/worldstate.sqlite3`) | 8 (`WORLD_SCHEMA_VERSION`) | `ensure_world_database()` |

At runtime both files are accessed through a single shared connection,
`server/state/migrations.py:DatabaseHub`, which opens the profile DB and
`ATTACH`es the world DB as `world`. Both databases run in WAL mode
(`PRAGMA journal_mode = WAL` on `main` plus `PRAGMA world.journal_mode = WAL`
after attach). All repository SQL therefore addresses
world tables as `world.room_cards`, `world.room_states`, and so on. `DatabaseHub`
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
(single-query batch used for room occupants); mutated by `set_sticker()` and
`issue_session()` (bumps `active_session_generation`). Friends, and Action Log
visibility live in `user_profiles.profile_json` (mutated by
`set_show_activity_log()`); owned rooms live in `user_profiles.ownership_json`.
Serialized to the client in `server/app.py:_serialize_account()` (wire
`owned_rooms` / `show_activity_log` keys).

| Column | Type | Description |
| --- | --- | --- |
| `id` | TEXT PK | Account UUID (`uuid4`). Referenced by `sessions`, `profile_card_stacks`, `user_profiles`. |
| `username_display` | TEXT NOT NULL | Username with original casing, shown in UI/presence. |
| `username_key` | TEXT NOT NULL UNIQUE | Casefolded username for uniqueness/login lookup (`normalize_username()`). |
| `password_hash` | TEXT NOT NULL | scrypt hash (`scrypt$n$r$p$salt$digest`), see `server/security.py:hash_password()` / `verify_password()`. |
| `sticker` | TEXT NULL | Chosen sticker filename under `data/stickers`; NULL until confirmed. Set once by `set_sticker()`. |
| `initial_sticker_complete` | INTEGER NOT NULL DEFAULT 0 | Boolean. Gates world entry (`/ws` closes `4403` until true). |
| _(removed)_ `favorites_json` | — | Core-card favorites were removed; all core cards are always visible. |
| `level` | INTEGER NOT NULL DEFAULT 0 | Progression level (Milestone 1: always 0 for new users; future use per `data/core/levels.yaml`). |
| `kudos` | INTEGER NOT NULL DEFAULT 0 | Kudos balance (future level-up currency). |
| `bops` | INTEGER NOT NULL DEFAULT 10 | Bops balance (future spendable currency). |
| `shared_energy` | INTEGER NOT NULL DEFAULT 80 | Shared energy pool (future juice system, cf. `data/core/juice.yaml`). |
| `last_energy_at` | TEXT NOT NULL | ISO timestamp of last energy update/recharge baseline. |
| `last_daily_claim` | TEXT NULL | ISO timestamp/date of last daily Bops claim; NULL if never claimed. |
| _(removed)_ `friends_json` / `pending_friends_json` | — | Moved into `user_profiles.profile_json.friends` (Milestone 1: `[]`). |
| `active_session_generation` | INTEGER NOT NULL DEFAULT 0 | Incremented on every `issue_session()`; enforces one live gameplay session (old sockets get `session.replaced`). |
| _(removed)_ `show_activity_log` | — | Moved into `user_profiles.profile_json.show_activity_log` (boolean, hidden by default; toggled by `.settings action-log`). |
| `created_at` | TEXT NOT NULL | ISO creation timestamp. |
| `updated_at` | TEXT NOT NULL | ISO last-update timestamp (bumped on sticker/settings/session changes). |
| `powers` | TEXT NOT NULL DEFAULT '[]' | JSON array of granted power names (`admin`, `realtor`, `builder`, `moderator`, `game-master`). Written by `server/services/powers.py:PowersService.grant()` / `revoke()`; each change is recorded in `audit_log`. |
| `muted_until` | TEXT NULL | ISO mute-expiry timestamp; NULL when not muted. Written by `PowersService.mute()` / `unmute()`. |
| `muted_by` | TEXT NULL | Account id of the moderator who applied the current mute. |

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

### 2.4 `user_profiles`

One row per user (PK `account_id`). Created by `create_account()` and lazily
by `ensure_user_profile()`; read by `get_user_profile()` and
`RoomService.current_room_for_account()`; `last_world_id` / `remembered_room`
/ `last_visit_at` updated by `set_remembered_room()` on every `.go`
(`server/services/rooms.py`) and used for resume on WS connect and
`/api/bootstrap` (`server/app.py:_serialize_account()`). Tasks, memories,
ownership, and the remaining gameplay blobs are unified per user rather than
per `(account, world)`. The `*_json` gameplay blobs are Milestone 1
placeholders (defaults below) reserved for later milestones.

| Column | Type | Description |
| --- | --- | --- |
| `account_id` | TEXT PK, FK → `accounts(id)` ON DELETE CASCADE | Owning account; single row per user. |
| `last_world_id` | TEXT NOT NULL | Last visited world (e.g. tutorial world). Set at signup; updated on world switch and every `.go`. |
| `remembered_room` | TEXT NULL | Last room the user occupied; WS connect resumes here if still in the world, else falls back to the entry room. |
| `native_cards_json` | TEXT NOT NULL | JSON dict of world-native card state (Milestone 1: `'{}'`). |
| `counters_json` | TEXT NOT NULL | JSON dict of world counters; seeded with `STARTING_WORLD_COUNTERS` (health/max_health, cleanliness/max_cleanliness, constitution, dexterity, charisma, fanciness). |
| `buffs_json` | TEXT NOT NULL | JSON dict of active buffs: `{"instances": [BuffInstance payloads]}` (`server/game/buffs.py`), empty `'{}'` until a buff is applied. |
| `tasks_json` | TEXT NOT NULL | JSON dict of quest/task state (Milestone 1: `'{}'`). |
| `memories_json` | TEXT NOT NULL | JSON dict of memory flags (Milestone 1: `'{}'`). |
| `ownership_json` | TEXT NOT NULL | JSON dict of ownership claims: `{"rooms": [room_id, ...]}`. Drives the per-user `editable` flag on room snapshots. Empty `'{}'` until a realtor/task grants ownership (not yet wired). |
| `profile_json` | TEXT NOT NULL | JSON user profile: `{friends[], friend_requests_sent[], friend_requests_received[], pinned_peeps[], skills[], statuses[], show_activity_log bool, ui_settings{}}`; extensible for UI settings. Read with defaults merged (`_normalize_profile()`). |
| `last_visit_at` | TEXT NOT NULL | ISO timestamp of last room change; updated together with `remembered_room`. |

### 2.5 `reward_ledger`

Idempotency log guaranteeing that one-time rewards (kudos and/or cards) are
granted **exactly once** per account. Written and read by
`server/services/progression.py:ProgressionService` (`reward_once()` and the
shared `_grant()` insert). The check and insert happen inside the same
transaction as the balance update (`_grant()`), so a duplicate key returns
`False` without re-granting. Callers pass a stable key such as `task:portal`
or `seed:<index>:<card>` (`tools/seed_review_account.py`). Dialog choices also
use this ledger for idempotency: `DialogService.choose()` claims a
`dialog:<peep_id>:<action_id>` key so a replayed choice applies no side
effects, and `ProgressionService.has_ledger_entry()` reads the key without
writing.
Note this table lives in the profile DB (not the world DB) so rewards are
unified per account across worlds; `world_id` records where each grant occurred.

| Column | Type | Description |
| --- | --- | --- |
| `ledger_key` | TEXT PK (composite) | Caller-supplied reward identity (e.g. `task:portal`). Unique per account, not globally. |
| `account_id` | TEXT PK (composite), FK → `accounts(id)` ON DELETE CASCADE | Rewarded account. Indexed via `idx_reward_ledger_owner`. |
| `world_id` | TEXT NOT NULL | World active at grant time (informational). Part of `idx_reward_ledger_owner`. |
| `kind` | TEXT NOT NULL | Reward category (`reward`, `kudos`, `seed`, …); not constrained. |
| `payload_json` | TEXT NOT NULL CHECK `json_valid` | Placeholder for a future milestone: records grant details `{"kudos": int, "cards": [card_id, …]}` but is currently write-only (no reader), reserved for reward auditing/replay. |
| `created_at` | TEXT NOT NULL | ISO grant timestamp. |

### 2.6 `pack_purchases`

Idempotency log guaranteeing that a card-pack purchase is charged and its
results granted **exactly once** per `(account_id, operation_id)`. Written and
read by `server/services/shop.py:ShopService.purchase()`; the replay lookup, the
Bops debit, the card grants, and the insert all run inside a single
`DatabaseHub.transaction()`. A repeated `operation_id` returns the stored draw
(`replayed = True`, `bops_spent = 0`) without mutating balances or inventory.
Like `reward_ledger`, this table lives in the profile DB, so purchases are
unified per account across worlds.

| Column | Type | Description |
| --- | --- | --- |
| `operation_id` | TEXT PK (composite) | Client-supplied purchase identity from `.buy_pack <pack> <operation_id>` (1–80 chars). Unique per account, not globally. |
| `account_id` | TEXT PK (composite), FK → `accounts(id)` ON DELETE CASCADE | Purchasing account. Indexed via `idx_pack_purchases_owner`. |
| `pack_id` | TEXT NOT NULL | Pack definition ID from the catalog (`server/content/cards.py`). |
| `results_json` | TEXT NOT NULL CHECK `json_valid` | Ordered JSON list of drawn `card_def_id`s, replayed on a duplicate `operation_id`. |
| `created_at` | TEXT NOT NULL | ISO purchase timestamp. |

### 2.7 `task_progress`

One row per `(account_id, task_id)` for every task a user has started. Owned by
`server/services/tasks.py:TaskService` (started lazily by `start()` /
`start_in_transaction()`, advanced by `record()` / `advance_step()`). `steps_json`
stores ordered `[{step_id, progress}]`; completion grants its reward through
`reward_ledger` (`ledger_key = "task:<id>"`, or `"task:<id>:<game_day>"` for
repeatable tasks) exactly once and writes game memories. `definition_revision`
lets an edited task definition reset a stale row; repeatable tasks reset only
per `reset_policy` (currently `daily`, using the configured timezone).

| Column | Type | Description |
| --- | --- | --- |
| `account_id` / `task_id` | TEXT PK (composite), FK → `accounts(id)` | Owning account and authored task ID. |
| `world_id` | TEXT NOT NULL | World the task belongs to; indexed via `idx_task_progress_owner`. |
| `scope` | TEXT NOT NULL | `personal` or `shared`. |
| `status` | TEXT NOT NULL | `active` or `completed`. |
| `steps_json` | TEXT NOT NULL CHECK `json_valid` | Ordered per-step progress. |
| `started_at` / `completed_at` | TEXT | ISO timestamps; `completed_at` is NULL while active. |
| `definition_revision` | INTEGER NOT NULL DEFAULT 0 | Revision the stored progress was written against. |
| `reward_operation_id` | TEXT NULL | Ledger key of the granted reward (audit/replay). |
| `shared_owner_id` | TEXT NULL | World ID for shared tasks; NULL for personal. |

### 2.8 `memories`

Journal entries. Game memories are immutable (`editable = 0`) and written by
`TaskService`; manual memories (`editable = 1`, `source_type = 'manual'`) are
created/edited/deleted only by their owner through `server/services/memories.py:MemoryService`.
Month grouping and summaries use the configured timezone.

| Column | Type | Description |
| --- | --- | --- |
| `memory_id` | TEXT PK | `mem:<uuid4>`. |
| `account_id` | TEXT NOT NULL FK → `accounts(id)` ON DELETE CASCADE | Owning account; indexed via `idx_memories_owner`. |
| `world_id` | TEXT NOT NULL | World the memory belongs to. |
| `author` | TEXT NOT NULL | Display name captured at write time. |
| `source_type` | TEXT NOT NULL | `game` or `manual`. |
| `text` | TEXT NOT NULL | Memory body. |
| `tags_json` | TEXT NOT NULL CHECK `json_valid` | Tag list (includes `task:<id>` for task memories); indexed via `idx_memories_task`. |
| `task_id` | TEXT NULL | Owning task for game memories. |
| `created_at` | TEXT NOT NULL | ISO timestamp. |
| `editable` | INTEGER NOT NULL DEFAULT 0 | Boolean; only manual memories are editable. |

## 3. World-state DB — `TRSERVER_WORLDSTATE_PATH`

The world-state DB persists durable, shared room content: live card stacks
(`room_cards`) and per-room metadata (`room_states`). Chat history and broadcast
ordering are **not** persisted — `WorldStateRepository` keeps chat history in
memory, so it is lost on server restart. Because a single server process owns a
world, room operations are already serialized in-process and no per-room
sequence counter is needed.

World-state databases at an older supported version are migrated forward
additively; a fresh DB is required only for versions newer than this build
(`WORLD_SCHEMA_VERSION = 8`).

### 3.1 `room_states`

One row per room, created by
`server/state/world_state.py:WorldStateRepository.initialize_world()`. The
`initialized` flag controls YAML seeding: a room with `initialized = 0` (missing
row, fresh database, or a manually cleared flag) has its live cards deleted and
its YAML seed cards re-inserted on the next server start; a room with
`initialized = 1` is left untouched, so collected seeds stay collected and
dropped cards stay dropped across restarts. This replaces the former
room-exists gate that lived in the removed `rooms` table.

| Column | Type | Description |
| --- | --- | --- |
| `room_id` | TEXT PK | Room ID from `worlds/<world>/rooms/*.yaml` (every room in the loaded world definition is reachable). |
| `initialized` | INTEGER NOT NULL DEFAULT 0 | `0` = reseed cards from YAML on next server start; `1` = leave the room's live cards alone. |
| `owner_account_id` | TEXT NULL | Placeholder for a future milestone: reserved for room ownership (merges the former `room_owners` placeholder; currently written as NULL and never read). |
| `props_json` | TEXT NOT NULL DEFAULT `'{}'` | Placeholder for a future milestone: reserved JSON blob for dynamic prop state (merges the former `prop_states` placeholder; currently written as `'{}'` and never read). |

### 3.2 `room_cards`

Live card stacks lying in rooms. Seeded from `room.initial_cards` by
`initialize_world()` (uninitialized room) or `reset_room_cards()` (`.reset_room`);
listed by `list_room_cards()` for snapshots; mutated by `take_room_card()`
(pickup) and `add_room_card()` (drop) inside `CardService` transactions, each
broadcasting `room.card.added/updated/removed` (`server/services/cards.py`,
`server/commands/core.py`). `.reset_room` (`reset_room_cards()`) deletes every
live stack in the caller's room — including player drops — re-inserts the YAML
seeds, sets `room_states.initialized = 1`, and broadcasts `room.cards.reset`.

| Column | Type | Description |
| --- | --- | --- |
| `stack_id` | TEXT PK | Stack ID: `room:<seed key>` for seeded stacks, `room:<uuid4>` for dropped cards. Referenced by `.pickup @card:<stack_id>` and `.look @card:<stack_id>`. |
| `room_id` | TEXT NOT NULL | Containing room. Indexed via `idx_room_cards_room_id` and `idx_room_cards_order (room_id, created_at, stack_id)`, which covers the snapshot `ORDER BY`. |
| `card_def_id` | TEXT NOT NULL | Card definition ID from the catalog. |
| `quantity` | INTEGER NOT NULL | Cards in this stack. |
| `position_json` | TEXT NOT NULL | JSON board position triple `[x, y, z]`; seeded from YAML `pos`, drops land at `(50, 50, 0)` (`core.py`). Serialized as `position: [x, y, z]`. |
| `scope` | TEXT NOT NULL DEFAULT `'room'` | Always `'room'` in Milestone 1; mirrors the inventory `scope` vocabulary. |
| `pinned` | INTEGER NOT NULL DEFAULT 0 | Boolean. Pinned stacks reject `.pickup` (`take_room_card()`). |
| `created_at` | TEXT NOT NULL | ISO creation timestamp; list ordering key. |
| `updated_at` | TEXT NOT NULL | ISO last-quantity-change timestamp. |

Seeded stacks use a deterministic `stack_id` (`room:<seed key>`, where the
seed key is `<room>:<index>:<card>` from the content loader in
`server/content/worlds.py`); `room_cards` carries no `initial_key` column and
there is no seed ledger table. Restart safety comes from
`room_states.initialized`: only rooms flagged `0` are re-seeded, so collected
seeds stay collected and dropped cards stay dropped.

### 3.3 `behavior_state`

Per-instance state for trusted behavior scripts, keyed by `(namespace,
instance_id)` (`namespace` is `peep` or `prop`). Read and written by
`server/behaviors/dispatcher.py:BehaviorDispatcher` inside the intent
transaction; scripts never touch the database directly. State survives server
restarts so counters and prop environment values persist.

| Column | Type | Description |
| --- | --- | --- |
| `namespace` / `instance_id` | TEXT PK (composite) | Owning entity kind and ID. |
| `state_json` | TEXT NOT NULL CHECK `json_valid` | Script-managed JSON state. |
| `updated_at` | TEXT NOT NULL | ISO last-write timestamp. |

### 3.4 In-memory state (not persisted)

`WorldStateRepository` holds room chat history in a process-local dict, capped at
`MAX_HISTORY_MESSAGES` (50) entries of `{speaker_id, speaker, style, text}`.
`RoomService.say()` appends via `append_chat_message()`; snapshots include it via
`read_room_view()`. It is intentionally lost on server restart.

`DispenserService` keeps each dispenser prop's recharge instant in a process-local
dict keyed by `(world_id, instance_id)` (`server/services/dispensers.py`). It is
deliberately not persisted, so every dispenser starts ready after a server
restart. (The former `prop_cooldowns` world table was removed; an older database
may still contain it, unused.)
