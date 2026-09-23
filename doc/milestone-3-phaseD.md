# Milestone 3 — Phase D: Commands and Powers

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A–C must be complete.

## 1. What this phase delivers

World-local user powers (`admin`, `realtor`, `builder`, `moderator`,
`game-master`), the realtor/builder/moderator/game-master command sets, admin
`\` console forwarding with the `\r`/`\k` block, structured audit entries, mute
enforcement, and complete searchable command metadata/help.

Out of scope: room-edit UI (E), world-editor publish (F), activity result hooks
(G). Room-owner editing in Phase E depends on `OwnershipService.can_edit`, which
this phase completes.

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` sections *User Powers*, *Command Types*,
  *Commands and Administration*.
- `doc/milestone-3.md` work package 7.
- `server/commands/parser.py` (`\` admin kind), `server/commands/core.py`
  (`dispatch_command`, registry), `server/commands/outcomes.py`.
- `server/commands/gameplay.py` — command style examples.
- `server/connections.py` — `ConnectionRegistry`, `LiveConnection`, send/close.
- `server/services/rooms.py` — `RoomService.say` and navigation.
- `server/services/ownership.py` (Phase C) — `can_edit`.
- `server/services/stats.py`, `server/services/progression.py` — game-master levers.
- `server/services/environment.py` (Phase C) — environment control.
- `server/content/worlds.py` — `WorldDefinition`; add `powers:`.
- `server/config.py` — env parsing; add `TRSERVER_ADMINS`.
- `server/app.py` — `_serialize_account`, WS command loop, `create_runtime`.
- `app/js/ui.js` — command palette; `app/js/state.js` — bootstrap normalization.

### Hard rules
- Every source file **under 1200 lines**; split modules if needed.
- Python: `from __future__ import annotations`, type hints, docstrings on public
  functions, **no inline comments** except one or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- Command paths and UI paths must call the **same service methods and permission
  checks**; never duplicate authorization logic.
  
- Never infer admin from account creation order. Never `eval`/`exec` arbitrary
  user input.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Schema

Bump **profile** schema 5 → 6. Fresh-schema additions (`_PROFILE_TABLES`,
column specs, `_PROFILE_MIGRATIONS[6]`): the `accounts` columns `powers`,
`muted_until`, and `muted_by`, plus:

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id TEXT NOT NULL,
    actor_account_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    result TEXT NOT NULL,
    detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_world ON audit_log(world_id, created_at);
```

Powers and moderation are stored on the `accounts` row rather than in dedicated
tables: `powers TEXT NOT NULL DEFAULT '[]'` (JSON array) plus `muted_until` /
`muted_by`. The single schema 5 → 6 migration adds those columns and creates
`audit_log`; no separate power or moderation tables are created. Every grant,
revoke, mute, and unmute is recorded in `audit_log`.

### 3.2 Power source

- Add `powers:` to `world.yaml` as a mapping `username -> [power, ...]`; validate
  each power is in `POWER_NAMES` and each username is non-empty. Store
  casefolded usernames in `WorldDefinition.powers`.
- `server/config.py`: parse `TRSERVER_ADMINS` (comma-separated usernames) into
  `AppConfig.bootstrap_admins: frozenset[str]` (casefolded). Empty default.
- Create `server/services/powers.py` — `PowersService(hub, profiles, world,
  bootstrap_admins)`:
  - `POWER_NAMES = ("admin", "realtor", "builder", "moderator", "game-master")`.
  - `effective(account) -> frozenset[str]` = world.yaml map ∪ bootstrap admins ∪
    `accounts.powers` grants.
  - `has_power(account_id, power) -> bool`.
  - `grant(actor_id, target_account_id, power)` / `revoke(actor_id, target_account_id, power)`
    updating `accounts.powers`; both write an audit entry.
  - `is_muted(account_id) -> bool` from `accounts.muted_until > now`.
  - `mute(actor_id, target_account_id, minutes)` / `unmute(actor_id, target_account_id)`.
- `_serialize_account` adds `"powers": sorted(powers.effective(account))`.
- `CommandContext` gains `powers: PowersService`, `ownership`, `environment`,
  `audit`, and `connections`. Add `require_power(context, power)` in
  `server/commands/core.py` raising `CommandError` when absent.

### 3.3 Audit

Create `server/services/audit.py` — `AuditService(hub, world_id)` with
`record(actor_account_id, action, target, result, detail=None)` inserting into
`audit_log` with a UTC timestamp. Every privileged handler calls it on both
success and rejection; wrap handlers so an audit failure cannot break gameplay
(log and continue).

### 3.4 Realtor commands

Register `.own`:
- `.own grant <room_id> @<username>` — requires `realtor`; calls
  `OwnershipService.grant`.
- `.own remove <room_id>` — requires `realtor`; `OwnershipService.revoke`.
- `.own modify <room_id> @<username>` — requires `realtor`; replace owner.
- `.own show <room_id>` — requires `realtor`; returns current owner.
Audit each with the room and target.

### 3.5 Builder commands

Register `.builder`:
- `.builder grant @<username>` / `.builder revoke @<username>` — requires
  `admin`; grants/revokes the `builder` power.
- `.builder rooms` — requires `builder`; lists rooms with owner and revision.
Audit each. Room creation/deletion lives in the World Editor publish pipeline
(Phase F); expose a thin `.builder` command only where it delegates to the same
services.

### 3.6 Moderator commands and mute enforcement

Register:
- `.mute @<username> <minutes>` / `.unmute @<username>` — requires `moderator`.
- `.kick @<username> [reason]` — requires `moderator`; closes the target's live
  connection via `ConnectionRegistry` and broadcasts the reason.
Enforce mute:
- In `server/app.py` WS loop (or `RoomService.say`), reject `.say` from a muted
  account with a visible explanation. Other commands remain allowed.
- Mute is world-local and expires by timestamp; no cleanup job required.

### 3.7 Game-master commands

Register `.gm` subcommands, all requires `game-master`, all audited:
- `.gm give @<username> @card:<card_id> [quantity]` — grant via inventory service.
- `.gm setcounter @<username> <counter> <value>` — clamp to the effective maximum
  and reconcile statuses through `StatsService`.
- `.gm buff @<username> <buff_id> <duration_seconds>`.
- `.gm kudos @<username> <amount>`.
- `.gm environment <room_id> <key> <json_value>` — via `EnvironmentService`.
Never bypass domain validation; reuse the same services UI paths use.

### 3.8 Admin console

Create `server/commands/admin.py`:
- `AdminConsole` with an explicit allowlist: `help`, `status`, `rooms`, `audit`,
  `say <text>` (server announcement). No arbitrary code execution.
- `dispatch_admin(context, command)` — requires `admin`; reject command names
  `r` and `k` (and `r`/`k` prefixes) with a clear message before lookup. Audit
  every invocation.
- In `server/commands/core.py:dispatch_command`, replace the unconditional
  rejection of `command.kind == "admin"` with `await dispatch_admin(context, command)`.

### 3.9 Command metadata and help

- Extend `CommandSpec` (`server/commands/registry.py`) with optional `usage`,
  `power`, and `help` fields (defaults `""`/`None`).
- Update every `registry.register(...)` call to include usage/help; power-gated
  commands declare their power.
- `.help` payload becomes
  `{"commands": [{"name", "summary", "usage", "power", "help"}]}`.
- Client `app/js/ui.js` command palette: keep the search filter; show usage/help
  text; hide or disable entries whose `power` the user lacks (based on
  `user.powers`). Normalize `user.powers` in `app/js/state.js`.
- Admin console commands are only sent for users with `admin`; block typing `\r`
  and `\k` client-side with the same message the server returns.

## 4. Tests

Create `tests/test_milestone3_powers.py` (subclass
`tests/test_milestone2_integration.py:Milestone2IntegrationTestCase` for WS
paths, plus `ServiceTestCase` for services). Cover:
- Every power boundary through both a command and an HTTP/WS UI path.
- A user without a power is rejected; a granted power takes effect immediately.
- `\r` and `\k` are blocked for admins; other admin commands work and are audited.
- Non-admin `\` commands are rejected.
- Audit entries record actor, world, action, target, and result for success and
  rejection.
- Mute blocks `.say` but not other commands and expires.
- Kick closes the target socket.
- Bootstrap exposes `powers`; the help payload includes usage/help/power.

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] `world.yaml powers:` and `TRSERVER_ADMINS` both grant powers.
- [ ] No privileged path bypasses the service permission checks.
- [ ] All privileged actions are audited.
- [ ] `/help` searchable metadata is complete for every registered command.
- [ ] Every file under 1200 lines; existing tests pass.

## 6. Guardrails

- Do **not** special-case the first account as admin.
- Do **not** implement a generic Python/SQL console.
- Do **not** let a power held in one world grant authority in another; powers are
  world-local (`world.yaml`, env bootstrap, and per-world DB grants).
- Do **not** block unrelated gameplay when a mute is active.
