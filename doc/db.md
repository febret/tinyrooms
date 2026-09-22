# Tinyrooms — Database Reference

This document describes the SQLite schemas for the two databases used by the
Milestone 1 backend. The schema source of truth is
`server/state/migrations.py`; the runtime access layer is
`server/profiles.py` (profile DB) and `server/state/world_state.py` (world DB).

## 1. Overview

| Database | File | Schema version | Initialization entrypoint |
| --- | --- | --- | --- |
| Profile (user) DB | `<users_path>/profiles.sqlite3` | 3 (`PROFILE_SCHEMA_VERSION`) | `ensure_profile_database()` |
| World-state DB | `TRSERVER_WORLDSTATE_PATH` (default `.local/worldstate.sqlite3`) | 6 (`WORLD_SCHEMA_VERSION`) | `ensure_world_database()` |

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
`issue_session()` (bumps `active_session_generation`). Favorites, friends,
and Action Log visibility live in `user_profiles.profile_json` (mutated by
`toggle_favorite()` / `set_show_activity_log()`). Serialized to the client in
`server/app.py:_serialize_account()` (wire `favorites` / `show_activity_log`
keys unchanged).

| Column | Type | Description |
| --- | --- | --- |
| `id` | TEXT PK | Account UUID (`uuid4`). Referenced by `sessions`, `profile_card_stacks`, `user_profiles`. |
| `username_display` | TEXT NOT NULL | Username with original casing, shown in UI/presence. |
| `username_key` | TEXT NOT NULL UNIQUE | Casefolded username for uniqueness/login lookup (`normalize_username()`). |
| `password_hash` | TEXT NOT NULL | scrypt hash (`scrypt$n$r$p$salt$digest`), see `server/security.py:hash_password()` / `verify_password()`. |
| `sticker` | TEXT NULL | Chosen sticker filename under `data/stickers`; NULL until confirmed. Set once by `set_sticker()`. |
| `initial_sticker_complete` | INTEGER NOT NULL DEFAULT 0 | Boolean. Gates world entry (`/ws` closes `4403` until true). |
| _(removed)_ `favorites_json` | — | Moved into `user_profiles.profile_json.favorites` (list of core-card IDs favorited via `.favorite`). |
| `level` | INTEGER NOT NULL DEFAULT 0 | Progression level (Milestone 1: always 0 for new users; future use per `data/core/levels.yaml`). |
| `kudos` | INTEGER NOT NULL DEFAULT 0 | Kudos balance (future level-up currency). |
| `bops` | INTEGER NOT NULL DEFAULT 10 | Bops balance (future spendable currency). |
| `shared_energy` | INTEGER NOT NULL DEFAULT 80 | Shared energy pool (future juice system, cf. `data/core/juice.yaml`). |
| `last_energy_at` | TEXT NOT NULL | ISO timestamp of last energy update/recharge baseline. |
| `last_daily_claim` | TEXT NULL | ISO timestamp/date of last daily Bops claim; NULL if never claimed. |
| _(removed)_ `friends_json` / `pending_friends_json` | — | Moved into `user_profiles.profile_json.friends` / `.pending_friends` (Milestone 1: `[]`). |
| `active_session_generation` | INTEGER NOT NULL DEFAULT 0 | Incremented on every `issue_session()`; enforces one live gameplay session (old sockets get `session.replaced`). |
| _(removed)_ `show_activity_log` | — | Moved into `user_profiles.profile_json.show_activity_log` (boolean, hidden by default; toggled by `.settings action-log`). |
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
| `buffs_json` | TEXT NOT NULL | JSON dict of active buffs (Milestone 1: `'{}'`). |
| `tasks_json` | TEXT NOT NULL | JSON dict of quest/task state (Milestone 1: `'{}'`). |
| `memories_json` | TEXT NOT NULL | JSON dict of memory flags (Milestone 1: `'{}'`). |
| `ownership_json` | TEXT NOT NULL | JSON dict of ownership claims (Milestone 1: `'{}'`). |
| `profile_json` | TEXT NOT NULL | JSON user profile: `{favorites[], friends[], pending_friends[], show_activity_log bool, ui_settings{}}`; extensible for UI settings. Read with defaults merged (`_normalize_profile()`). |
| `last_visit_at` | TEXT NOT NULL | ISO timestamp of last room change; updated together with `remembered_room`. |

### 2.5 `reward_ledger`

Idempotency log guaranteeing that one-time rewards (kudos and/or cards) are
granted **exactly once** per account. Written and read by
`server/services/progression.py:ProgressionService` (`reward_once()`,
`grant_kudos()` with a `ledger_key`, `has_reward()`, and the shared `_grant()`
insert). The check and insert happen inside the same transaction as the balance
update (`_grant()`), so a duplicate key returns `False` without re-granting;
`has_reward()` offers a pre-check. Callers pass a stable key such as
`task:portal` or `seed:<index>:<card>` (`tools/seed_review_account.py`).
Note this table lives in the profile DB (not the world DB) so rewards are
unified per account across worlds; `world_id` records where each grant occurred.

| Column | Type | Description |
| --- | --- | --- |
| `ledger_key` | TEXT PK (composite) | Caller-supplied reward identity (e.g. `task:portal`). Unique per account, not globally. |
| `account_id` | TEXT PK (composite), FK → `accounts(id)` ON DELETE CASCADE | Rewarded account. Indexed via `idx_reward_ledger_owner`. |
| `world_id` | TEXT NOT NULL | World active at grant time (informational). Part of `idx_reward_ledger_owner`. |
| `kind` | TEXT NOT NULL | Reward category (`reward`, `kudos`, `seed`, …); not constrained. |
| `payload_json` | TEXT NOT NULL CHECK `json_valid` | JSON grant details: `{"kudos": int, "cards": [card_id, …]}`. |
| `created_at` | TEXT NOT NULL | ISO grant timestamp. |

## 3. World-state DB — `TRSERVER_WORLDSTATE_PATH`

The world-state DB persists durable, shared room content: live card stacks
(`room_cards`) and per-room metadata (`room_states`). Chat history and broadcast
ordering are **not** persisted — `WorldStateRepository` keeps chat history in
memory, so it is lost on server restart. Because a single server process owns a
world, room operations are already serialized in-process and no per-room
sequence counter is needed.

Old world-state databases are not migrated; this build requires a fresh
world-state DB (`WORLD_SCHEMA_VERSION = 6`).

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
| `room_id` | TEXT PK | Room ID from `worlds/<world>/rooms/*.yaml` (Milestone 1 playable: `hub`, `playroom`). |
| `initialized` | INTEGER NOT NULL DEFAULT 0 | `0` = reseed cards from YAML on next server start; `1` = leave the room's live cards alone. |
| `owner_account_id` | TEXT NULL | Reserved for future room ownership (merges the former `room_owners` placeholder; unused). |
| `props_json` | TEXT NOT NULL DEFAULT `'{}'` | Reserved JSON blob for future dynamic prop state (merges the former `prop_states` placeholder; unused). |

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

### 3.3 In-memory room state (not persisted)

`WorldStateRepository` holds room chat history in a process-local dict, capped at
`MAX_HISTORY_MESSAGES` (50) entries of `{speaker_id, speaker, style, text}`.
`RoomService.say()` appends via `append_chat_message()`; snapshots include it via
`read_room_view()`. It is intentionally lost on server restart.
