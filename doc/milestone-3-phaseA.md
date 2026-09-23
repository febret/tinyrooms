# Milestone 3 — Phase A: Behavior Runtime and Declarative Dialogs

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Do not start Phase B until this phase passes.

## 1. What this phase delivers

A trusted-script behavior subsystem (event dispatcher, typed context, room tick
loop, per-instance state) and declarative NPC dialogs shown through the Look Bar
and Quick Actions Bar. This is the foundation every later phase uses.

Out of scope: props/auras/crafting (Phase C), tasks/memories (Phase B), powers
(Phase D), editors (E/F), Lazor Rush (G).

## 2. Orientation (read these before coding)

Project: **Tinyrooms**, a multiplayer miniature-world game. Backend Python
3.11+ / FastAPI / SQLite; frontend vanilla ES modules + Three.js; YAML content
under `worlds/` and `data/`. The server is authoritative; the browser is a pure
renderer that sends command strings.

Read for context (do not modify yet):
- `AGENTS.md`, `doc/design.md` sections *Peeps*, *Dialogs*, *Room Design*.
- `doc/milestone-3.md` work packages 1 and 2.
- `doc/architecture.md` (components, protocol, flows).
- `server/content/worlds.py` — world/room/prop/peep loaders.
- `server/services/rooms.py` — snapshots and navigation.
- `server/commands/core.py`, `server/commands/outcomes.py`, `server/commands/registry.py`.
- `server/app.py` — runtime assembly (`create_runtime`) and the `/ws` loop.
- `server/state/migrations.py` — schema/migration mechanism.
- `server/profiles.py` — profile repository and `update_profile_in_transaction`.
- `server/services/progression.py` — idempotent reward ledger.
- `worlds/tutorial/peeps/peeps.yaml`, `worlds/tutorial/peeps/molly.py`, `worlds/tutorial/peeps/caretaker.py`.

### Hard rules
- All source files stay **under 1200 lines** (enforced by `tests/test_ui_presentation.py`). Split modules when close.
- Python: `from __future__ import annotations` at the top of every file; type hints on all public functions; docstrings on public cross-module functions; **no inline comments** unless a non-trivial algorithm needs one or two.
- Imports ordered: stdlib, third-party, then `server.*`, each group separated by a blank line.
- No `localStorage`/`sessionStorage`; server is authoritative.
- Never commit secrets. Do not edit checked-in visual baselines.
- Run Python tests from an activated venv: `python -m unittest discover -s tests -v`.

### Existing scaffolding to activate
- `PeepDefinition.script_name` (`server/content/worlds.py`) is loaded but never imported.
- `PeepDefinition.dialog` is loaded as a raw dict, unvalidated and never serialized.
- `PropInstanceDefinition.behavior` is loaded and echoed to the client only.
- `worlds/tutorial/peeps/molly.py` uses an old `on_action(context, action, ...)` signature; `caretaker.py` calls a nonexistent `context.engine.dispatcher.start_dialog`.
- Quick actions are filtered to `.go/.inspect/.look/.play/.shop` in `RoomService._normalize_quick_action` (`server/services/rooms.py`); authored `.talk`/`.pet` actions are currently dropped.

## 3. Work

### 3.1 Schema (do this first)

Bump **profile** schema 3 → 4 and **world** schema 6 → 7 in
`server/state/migrations.py`.

Profile fresh-schema additions (also add to `_PROFILE_TABLES` and column specs):

```sql
CREATE TABLE IF NOT EXISTS active_dialogs (
    account_id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    peep_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    state_json TEXT NOT NULL CHECK (json_valid(state_json)),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS dialog_actions (
    account_id TEXT NOT NULL,
    peep_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, peep_id, action_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dialog_actions_owner ON dialog_actions(account_id);
```

World fresh-schema addition (also add to `_WORLD_TABLES` and column specs):

```sql
CREATE TABLE IF NOT EXISTS behavior_state (
    namespace TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (namespace, instance_id)
);
```

Add `_PROFILE_MIGRATIONS[4]` and a new `_WORLD_MIGRATIONS` dict with entry `7`
that create the tables above and set `PRAGMA user_version` to the new value.
`ensure_world_database` currently passes no `migrations=`; add
`migrations=_WORLD_MIGRATIONS`. Update `PROFILE_SCHEMA_VERSION = 4`,
`WORLD_SCHEMA_VERSION = 7`, the `_*_COLUMNS` tuples, and the `column_specs`
passed by both `ensure_*_database` functions.

### 3.2 Dialog content validation

In `server/content/worlds.py` add a `DialogDefinition` (nodes keyed by ID) and
`DialogChoice` dataclass. Validate each peep `dialog` mapping:
- `start` node must exist.
- Every node needs non-empty `text`.
- Every choice needs a `label`; it must have exactly one of `next` (existing node ID) or `end: true`.
- Optional `when` condition mapping (`{counter, at_or_below|above|at_or_above_fraction}`, same vocabulary as `server/content/gameplay.py` conditions) and optional `script`/`action` string.
- Reject dangling `next` targets (`ContentError`).
- Reject nodes unreachable from `start` unless the node ID starts with `unused_` (explicit opt-out for authored-but-hidden nodes).
- Store the validated tree as `PeepDefinition.dialog: DialogDefinition | None`.

### 3.3 Behavior package

Create `server/behaviors/` with:

**`events.py`** — frozen dataclasses:
- `PeepRef(kind: str, peep_id: str | None, account_id: str | None)` where `kind ∈ {"user","npc"}`.
- `PropRef(instance_id: str, prop_id: str, room_id: str)`.
- `BehaviorEvent(type: str, actor: PeepRef, target: PeepRef | PropRef | None, room_id: str | None, action: str | None, data: Mapping[str, object])`. `type ∈ {"tick","enter","leave","quick_action","card_play","dialog_action","activity_result"}`.

**`context.py`** — `BehaviorContext` plus `Intent`:
```python
@dataclass(frozen=True, slots=True)
class Intent:
    kind: str
    payload: dict[str, object]
```
`BehaviorContext` fields: `event`, `actor`, `target`, `room` (read-only mapping:
`id/label/props/peeps/exits`), `world` (read-only `id/label`), `state` (mutable
per-instance `dict`), `now` (UTC datetime), and `intents: list[Intent]`.
Methods (each appends an `Intent`; never mutates live services directly):
`feedback(text, style="toast")`, `effect(effect_id)`, `apply_counter(counter, delta)`,
`apply_buff(buff_id, duration_seconds=None, daily=False, source=None)`,
`grant(kudos=0, cards=(), ledger_key=None)`, `give_card(card_id, quantity=1)`,
`start_dialog(peep_id, node_id=None)`, `end_dialog()`, `start_activity(kind, title=None)`,
`start_task(task_id)`, `update_task_progress(task_id, step_id=None, amount=1)`,
`request_move(room_id)`, `set_environment(key, value)`.
Optional `target` argument on effect-producing methods defaults to the event
actor. Expose `context.prop_state(key, default=None)` reading `self.state`.

**`loader.py`** — `BehaviorLoader`:
- `load_world(world) -> BehaviorScripts` imports, at definition time only, one
  module per script via `importlib.util.spec_from_file_location`. Cache by
  resolved path. Use a stable module name `tinyrooms_behavior_<sha1(path)>`.
- Peep scripts resolve to `<world.root_path>/peeps/<script_name>`. Prop scripts
  resolve to `<world.root_path>/props/<script>` (relative path allowed).
- Missing files raise `ContentError` at load. No filesystem watching, no reload.

**`dispatcher.py`** — `BehaviorDispatcher` (constructed in `create_runtime`):
- `async def dispatch(self, event, *, extra=None) -> BehaviorResult` where
  `BehaviorResult` holds `messages`, `private_events`, `room_broadcasts`,
  `snapshots` (mirroring `CommandOutcome` fields).
- Select targets: for `tick`/`enter`/`leave` all scripts attached to the room;
  for `quick_action`/`card_play` the target peep/prop script; for
  `dialog_action`/`activity_result` the referenced script plus scripts exporting
  that handler.
- Call the handler named `on_<type>` if the module defines it; handlers receive
  `(context, event)` and may be sync; `async` handlers are awaited.
- Run in a `try/except Exception`: on error, log a structured record
  `{"event":"behavior.error","script":…,"event_type":…,"error":…}`, record the
  script in `self.erroring`, and return a rejected `BehaviorResult` **without
  applying any intent**. One script error never raises through the room loop.
- If no error, apply all intents through services inside one
  `hub.transaction()`: use `StatsService`, `ProgressionService`, `ActivityService`,
  `CardService.grant_card_to_inventory`, the dialog service, room mutation, and
  environment (Phase C stub that stores unknown keys in prop state until C
  lands). Every application is revalidated; unknown intent kinds are logged and
  skipped.
- `slow_handlers` threshold: log when a handler takes more than 0.25s.

**`ticker.py`** — `RoomTicker`:
- One asyncio task per room, interval `config.tick_seconds` (default 1.0).
- Overlap guard: skip a tick for a room whose previous tick is still running.
- Skip offline users (only dispatch for connected connections in the room;
  NPCs always tick).
- Started in `create_runtime`/lifespan start and cancelled on shutdown; expose
  `start()`, `stop()`, `run_once(room_id)` for tests.

**`builtin.py`** — `BUILTIN_BEHAVIORS: dict[str, str]` mapping the authored
`behavior:` strings to a no-op registration for now; the dispatcher may map a
prop's `behavior` to a synthetic script id `builtin:<name>`. Concrete behavior
implementations arrive in Phase C; keep this file small.

### 3.4 Dialog service

Create `server/services/dialogs.py` — `DialogService`:
- `start(account, peep_id, node_id=None) -> ActiveDialog`: validates the peep is
  present in the account's current room and the node exists; upserts
  `active_dialogs` (one row per account, replacing any previous dialog).
- `view(account_id) -> ActiveDialog | None`.
- `choose(account, choice_index_or_action_id, *, action_id: str) -> DialogResult`:
  - Revalidate active dialog, peep presence, node, and each choice's `when`
    condition; reject on any mismatch.
  - Idempotency: insert `(account_id, peep_id, action_id)` into
    `dialog_actions`; a duplicate returns the stored node and applies no side
    effects. Side effect + node transition happen in the same transaction.
  - Side effects: optional `script`/`action` callback dispatched as a
    `dialog_action` behavior event; optional declarative side effects
    (`give_card`, `start_task`, `grant`) resolved through services.
  - On `end: true`, delete the row.
- `end(account_id, reason)`: deletes the active dialog.
- Serialize `{peep_id, node_id, text, choices:[{label, index, action_id, disabled}]}`.
- Register `DialogService` in `server/app.py:create_runtime` / `RuntimeState` and
  in `CommandContext` (`server/commands/outcomes.py`).

### 3.5 Commands and events

Add to `server/commands/core.py` registry:
- `.talk <target>` — target is `@peep:<id>` or `@<username>`; starts (or
  re-focuses) the peep dialog at its `start` node; emits the dialog view in the
  result payload.
- `.act <action> <target>` — dispatches a `quick_action` behavior event with the
  given `action` to the target peep or prop instance; scripts return flavor via
  `context.feedback`. Authored peep actions (for example `.act pet @peep:molly`)
  route through this generic command so behavior semantics stay in YAML + script.
- `.dialog <index>` — chooses a dialog choice (revalidated server-side).
- `.dialog_end` — yellow Exit Conversation action; ends the dialog.
- Extend `RoomService._normalize_quick_action` to allow `.talk`, `.act`,
  `.dialog`, `.dialog_end`, and any authored command whose verb is registered in
  the command registry. Preserve existing `.go` normalization.
- `RoomService.serialize_npc` must emit the peep's authored `actions` plus a
  `Look` action instead of only `Look`.

Dispatch behavior events:
- `on_enter`/`on_leave`: call `BehaviorDispatcher` from `RoomService.navigate`
  (and WS connect/disconnect in `server/app.py`) and merge its result into the
  navigation outcome.
- `on_quick_action`: from `.talk`/`.act` and any prop action command.
- `on_card_play`: from `.use` when the action has a target (`server/commands/gameplay.py`).
- `on_dialog_action`: from `DialogService.choose`.
- `on_activity_result`: reserved; emit from Phase G.
- `on_tick`: from `RoomTicker`.

Update `worlds/tutorial/peeps/molly.py` and `caretaker.py` to the new API:
`def on_quick_action(context, event): ...` and `def on_dialog_action(...)`.
Keep behavior identical to the authored YAML dialogs; `molly.py` may return a
`context.feedback` for `pet`; `caretaker.py` may `context.start_dialog("caretaker", "start")`.

### 3.6 Client

- Room snapshot / dialog payload must include the active dialog:
  `RoomService.build_snapshot` adds `"dialog": <serialized or null>`.
- `app/js/state.js`: normalize `room.dialog`; in `app/js/ui.js` render dialog text
  in the Look Bar and dialog choices as Quick Action pills, plus a yellow
  `Exit Conversation` pill issuing `.dialog_end`.
- `app/js/cards.js` `selectionActions` must surface dialog choices when a dialog
  is active and the selected entity is the dialog's peep.
- Do not create a new board-modal view; dialogs live in the existing bars.

## 4. Tests

Create `tests/test_milestone3_behaviors.py` (subclass
`tests/common.py:ServiceTestCase`) and `tests/test_milestone3_dialogs.py`.
Cover, at minimum:
- Handler dispatch for every event type.
- Tick non-overlap (a slow handler does not start a second concurrent tick).
- Per-instance state persistence across a restart (reopen the hub).
- Script error containment + rollback: a handler that raises leaves counters
  unchanged and does not stop the tick loop.
- Dialog branching, hidden choices (`when` false), side effects, invalid/stale
  choice, departure cancellation on `.go`, and duplicate `action_id`.
Add a browser flow to `tests/browser/flows.spec.js` that opens a dialog, chooses
an option, and exits. Assert command frames as existing flows do.

## 5. Verification (run all, fix failures)

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] Fresh and migrated databases both initialize (test `test_milestone2_migrations.py` still passes).
- [ ] Every file under 1200 lines.
- [ ] Tutorial world loads with both peep scripts; no import errors.
- [ ] `molly.py`/`caretaker.py` use the new typed API.
- [ ] No rejected dialog choice changes state; duplicate `action_id` is a no-op.
- [ ] Existing tests (`test_milestone1.py`, `test_milestone2_*`) still pass.

## 6. Guardrails

- Do **not** let scripts mutate live objects; only intents applied by the dispatcher.
- Do **not** add per-room sequence counters; ordering comes from the single event loop.
- Do **not** reload scripts on filesystem changes; only at startup (and later publish).
- Do **not** add comments to YAML or code beyond one or two lines for tricky logic.
