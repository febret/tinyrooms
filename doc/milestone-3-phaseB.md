# Milestone 3 — Phase B: Journal (Tasks and Memories)

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phase A must already be complete (behavior events and
> the `BehaviorContext.update_task_progress`/`start_task` intents exist).

## 1. What this phase delivers

Persistent, idempotent Tasks and Memories with a complete Journal UI: active and
completed task lists, ordered multi-step progress, personal/shared credit,
timezone-correct monthly memory aggregation, manual memory create/edit/delete,
and task-tagged memory filtering.

Out of scope: behavior dispatch internals (A), props/crafting/auras (C), powers
(D), editors (E/F), Lazor Rush (G). `New Memory` saves the current Chat Bar text
but the chat-input plumbing is UI-only here.

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` section *The Journal*, `doc/milestone-3.md`
  work package 4.
- `doc/db.md` — profile DB schema and the placeholders `tasks_json` /
  `memories_json` in `user_profiles`.
- `server/state/migrations.py` — migration mechanism (now at profile version 4
  after Phase A).
- `server/profiles.py` — `ProfileRepository`, `get_account_by_id`,
  `update_profile_in_transaction`, `get_user_profile`.
- `server/content/gameplay.py` — condition parsing vocabulary
  (`at_or_below` / `above` / `at_or_above_fraction`) and strict loader style.
- `server/content/worlds.py` — content loader patterns and `ContentError`.
- `server/services/progression.py` — `reward_once(account_id, ledger_key, kudos=…, cards=…)`.
- `server/commands/core.py`, `server/commands/outcomes.py`, `server/commands/registry.py`.
- `server/app.py` — `_serialize_account` and `create_runtime`.
- `server/security.py` — `utc_now()`.
- `server/config.py` — `timezone` setting.
- `app/js/views/journal-view.js`, `app/js/state.js`, `app/js/ui.js`,
  `app/js/cards.js`, `app/css/cards.css` — current Journal stub.
- `tests/common.py`, `tests/test_milestone2_progression.py` — test patterns.

### Hard rules
- Every source file **under 1200 lines**; split modules if needed.
- Python: `from __future__ import annotations`, type hints on public functions,
  docstrings on public cross-module functions, **no inline comments** except one
  or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- No `localStorage`/`sessionStorage`.
- Persist UTC; compute game-day/month boundaries using `config.timezone`.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Schema

Bump **profile** schema 4 → 5 in `server/state/migrations.py`.

Fresh-schema additions (add to `_PROFILE_TABLES`, column specs, and
`_PROFILE_MIGRATIONS[5]`):

```sql
CREATE TABLE IF NOT EXISTS task_progress (
    account_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('personal', 'shared')),
    status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
    steps_json TEXT NOT NULL CHECK (json_valid(steps_json)),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    definition_revision INTEGER NOT NULL DEFAULT 0,
    reward_operation_id TEXT,
    shared_owner_id TEXT,
    PRIMARY KEY (account_id, task_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_progress_owner ON task_progress(account_id, world_id);
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    author TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('game', 'manual')),
    text TEXT NOT NULL,
    tags_json TEXT NOT NULL CHECK (json_valid(tags_json)),
    task_id TEXT,
    created_at TEXT NOT NULL,
    editable INTEGER NOT NULL DEFAULT 0 CHECK (editable IN (0, 1)),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(account_id, world_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memories_task ON memories(account_id, task_id);
```

Update `PROFILE_SCHEMA_VERSION = 5` and the `_USER_PROFILES_COLUMNS`-style specs
for the new tables.

### 3.2 Task definitions (content)

Create `server/content/tasks.py` — `load_task_definitions(world_path, card_ids)`
reading `worlds/<world>/tasks.yaml`. Dataclasses:
- `TaskStep(step_id, trigger, amount=1, title="", memory_tag=None)` where
  `trigger` is an event name (`go`, `card_play`, `dialog_action`,
  `activity_result`, `prop_action`, `enter_room`) plus a `match` mapping of
  required fields.
- `TaskReward(kudos=0, cards=())`.
- `TaskDefinition(id, scope, title, description, steps, reward, memory_tags,
  repeatable=False, reset_policy=None, participants="personal", revision=1)`.
  `scope ∈ {"personal","shared"}`. For shared tasks, `participants` lists
  usernames/peep IDs or `"room"`, and the definition states `credit` and
  `reward_recipients` (`"actor"` or `"all_participants"`).
- Validate: unique step IDs, contiguous order, non-empty title, rewards reference
  known cards, `revision >= 1`, repeatable tasks must declare `reset_policy`.
- Add `tasks: dict[str, TaskDefinition]` to `WorldDefinition` and load it in
  `load_world_definition` (`server/content/worlds.py`).

### 3.3 Services

Create `server/services/tasks.py` — `TaskService(hub, profiles, stats,
progression, content, world_id, task_definitions, timezone)`:
- `list_for_account(account_id) -> list[TaskView]` with active/completed
  separation, per-step progress, and definition revision.
- `start(account_id, task_id)` — lazily creates `task_progress`
  (`status="active"`, zeroed steps). Starting an already-active task is a no-op.
- `record(account_id, trigger: str, fields: Mapping[str, object], *, source=None)`:
  advance matching active task steps by `amount` (step order enforced: a later
  step cannot advance before earlier steps complete). When all steps complete:
  set `status="completed"`, `completed_at`, and call `progression.reward_once`
  with `ledger_key=f"task:{task_id}"` exactly once. Write a game-generated
  memory per `memory_tags`. Idempotent across duplicate events, reconnects, and
  restart. Repeatable tasks reset only per `reset_policy` after completion.
- Shared tasks: credit/rewards follow the definition policy; **room presence
  alone never grants credit**. Never crediting a participant who did not trigger
  the matching event.
- `view_payload(account_id) -> dict` for the bootstrap/snapshot.

Create `server/services/memories.py` — `MemoryService(hub, profiles, world_id,
timezone)`:
- `create_game(account_id, text, tags, *, task_id=None)` — immutable
  (`editable=0`), author is the account.
- `create_manual(account_id, text)` — `editable=1`, `source_type="manual"`.
- `edit_manual(account_id, memory_id, text)` / `delete_manual(account_id, memory_id)`
  — reject non-owners and non-manual memories; never touch task/reward history.
- `month_summary(account_id, year, month) -> dict` using the configured
  timezone: per-day memory counts, tasks completed in the month, Kudos earned
  (delta from `reward_ledger`), and new friends (from the friends profile).
- `list_month(account_id, year, month)` sorted by `created_at`.

### 3.4 Wiring

- Add `TaskService` and `MemoryService` to `RuntimeState` (`server/app.py`) and
  `CommandContext` (`server/commands/outcomes.py`).
- In `BehaviorDispatcher` intent application (Phase A), handle
  `start_task` and `update_task_progress` by calling `TaskService`.
- Call `TaskService.record` from the relevant command/event points:
  `.go`/`on_enter` (`enter_room`), `.use` card plays (`card_play`),
  dialog choices (`dialog_action`), prop actions (`prop_action`), and Phase G
  activity results (`activity_result`). Guard every call so a malformed trigger
  never raises through the command.
- `_serialize_account` adds `"tasks": task_service.view_payload(account.id)`
  and `"journal": memory_service.journal_payload(account.id)`.
- `RoomService.build_snapshot` need not embed tasks; the client already receives
  them from bootstrap and after task commands.

### 3.5 Commands

Register in `server/commands/core.py`:
- `.tasks` — list tasks (payload).
- `.task <task_id>` — select/view one task (payload).
- `.memories [year month]` — list a month (payload).
- `.memory_new` — create a manual memory from the current Chat Bar text passed as
  the command argument. The client sends `.memory_new <text>`; reject empty or
  over 280 chars.
- `.memory_edit @memory:<id> <text>`, `.memory_delete @memory:<id>`.
Extend `server/commands/parser.py` target parsing with `@memory:<id>`.

### 3.6 Client

Replace the stub in `app/js/views/journal-view.js` (keep it, plus a new
`app/js/journal.js` helper module if it gets large):
- Tasks tab: active and completed groups; each task shows title, description,
  ordered step progress; selecting a task updates Look Bar + Quick Actions.
- `Memories` quick action on a selected task opens the Memories tab filtered by
  that task's tag.
- Memories tab: reuse the existing calendar layout (`journal-view.js:4-27`,
  `state.js` month reducer `journalMonthOffset`); populate markers and month
  stats from the server payload; scrollable month list below.
- `New Memory` quick action saves the current `#chat-input` text via
  `.memory_new`; manual memories show `Edit`/`Delete` actions; game memories show
  neither.
- Add CSS to `app/css/cards.css` in the existing Journal block; do not restyle
  unrelated views.
- Normalize the new bootstrap keys in `app/js/state.js`.

## 4. Tests

Create `tests/test_milestone3_tasks.py` and `tests/test_milestone3_memories.py`
(subclass `tests/common.py:ServiceTestCase`). Cover:
- Personal credit fires only for the actor; shared credit per policy; presence
  alone never credits.
- Ordered multi-step progress (out-of-order triggers do not advance).
- One-time reward exactly once across duplicate events and a reopen/restart.
- Repeat reset rules only apply when declared.
- Reconnect replay does not duplicate progress or rewards.
- Manual memories: owner-only edit/delete; game memories immutable.
- Editing/deleting a memory never changes task progress/rewards.
- Timezone month aggregation: memories near a month boundary land in the correct
  month; month summary counts match.
Add a browser flow in `tests/browser/flows.spec.js` for the task list and the
monthly memory view.

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] Journal renders real active/completed tasks, steps, and memories.
- [ ] Monthly calendar markers and summary come from the server.
- [ ] New Memory round-trip works from the Chat Bar text.
- [ ] All rewards are idempotent across duplicate events and restart.
- [ ] Every file under 1200 lines; existing tests still pass.

## 6. Guardrails

- Do **not** grant task credit from room presence.
- Do **not** auto-repeat tasks; repeat requires an explicit `reset_policy`.
- Do **not** store game-day boundaries as UTC dates; use the configured timezone.
- Do **not** let memory edits mutate `task_progress` or `reward_ledger`.
- Do **not** animate or comment gratuitously; match existing code style.
