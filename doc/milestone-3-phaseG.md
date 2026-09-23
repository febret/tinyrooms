# Milestone 3 — Phase G: Activity Completion Hooks and Lazor Rush

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A–F must be complete.

## 1. What this phase delivers

Generic, signed activity result hooks on the server (start cost, result
validation, record, reward, abandon, close) and the real **Lazor Rush** engine
with explicit Start/Play Again, a 1-Energy start cost, continuous acceleration,
pointer/touch laser, fair visible-body collision, no pause when minimized or
covered, and separate personal/world records.

Out of scope: final tutorial task/reward wiring (Milestone 4). This phase records
results and exposes the `activity_result` task trigger; it does not hard-code
tutorial rewards.

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` sections *Activities*, *Lazor Rush*.
- `doc/milestone-3.md` work package 9 and the *Data and publishing rules*.
- `server/services/activities.py` — `ActivityService`, session serialization.
- `server/app.py` — `/api/activities/{id}/bridge`, `_serialize_account`.
- `server/commands/core.py:play_command` — `.play molly` → `lazor-rush` mapping.
- `server/services/stats.py` — Energy charging/reconciliation.
- `server/services/progression.py` — idempotent ledger.
- `server/services/tasks.py` (Phase B) — `record("activity_result", ...)`.
- `server/services/audit.py` (Phase D).
- `server/config.py` — features.
- `server/security.py` — hashing/UTC helpers.
- `activities/shared.js`, `activities/shared.css`, `activities/shop/`,
  `activities/dev-sample/` — activity bridge and examples.
- `activities/lazor-rush/index.html` — current redirect stub to replace.
- `app/js/activities.js` — activity window manager (min/max/covered, bridge).
- `tests/browser/fixtures.js` — browser harness notes; `tests/browser/flows.spec.js`.

### Hard rules
- Every source file **under 1200 lines**; split modules if needed.
- Python: `from __future__ import annotations`, type hints, docstrings on public
  functions, **no inline comments** except one or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- Activities are server-authoritative: the client only renders and sends signed
  results; the server validates every result and never trusts client timing.
- Never trust an unsigned or replayed result.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Schema

Bump **profile** schema 7 → 8 and **world** schema 9 → 10.

Profile (`_PROFILE_TABLES`, column specs, `_PROFILE_MIGRATIONS[8]`):

```sql
CREATE TABLE IF NOT EXISTS activity_operations (
    account_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    activity_kind TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, operation_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
```

World (`_WORLD_TABLES`, column specs, `_WORLD_MIGRATIONS[10]`):

```sql
CREATE TABLE IF NOT EXISTS activity_records (
    account_id TEXT NOT NULL,
    activity_kind TEXT NOT NULL,
    best_seconds REAL NOT NULL CHECK (best_seconds >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, activity_kind)
);
```

### 3.2 Signed activity events

- `ActivitySession` gains `secret: str` (generated with `secrets.token_urlsafe`
  when the session starts) and `config: dict` already used by the bridge.
- The host state sent to the iframe includes `activity.token` (the signed token)
  and `activity.config`. The token payload is
  `f"{account_id}:{activity_id}:{kind}"`; the signature is
  `hmac.new(secret, payload, sha256).hexdigest()`.
- Extend `activities/shared.js` with `TinyActivity.result({operationId, result})`
  that posts `tinyrooms.activity.result`.
- Extend `app/js/activities.js` to forward `tinyrooms.activity.result` to
  `POST /api/activities/{id}/bridge` with `type: "activity.result"`.
- Extend the bridge endpoint allowlist with `activity.result`; validate the
  session's `secret` signature, the account match, and the `operation_id` before
  handing off to the result service. Reject tampered/replayed results with a
  visible explanation and no state change.

### 3.3 Result service

Create `server/services/activity_results.py` — `ActivityResultService(hub,
profiles, stats, progression, tasks, world_id, definitions)`:
- Activity definitions (cost, min duration, record kind) live in
  `data/core/activities.yaml` or the world; use a small strict loader that
  defines `lazor-rush` with `start_cost=1`, `record=True`,
  `min_completed_round=0`. Validate.
- `start(account, kind, operation_id) -> StartResult`: idempotent (ledger via
  `activity_operations`); charge `start_cost` Energy through `StatsService`;
  reject when unaffordable; Tired behavior follows normal Energy rules (a paid
  round continues even if the cost makes the user Tired, but starting another is
  blocked until recovery). Record `start` state.
- `complete(account, kind, operation_id, result) -> CompleteResult`:
  idempotent by `operation_id`; validate `result` shape
  (`{seconds: float >= 0, captured: bool}`); record a personal best and update the
  world all-time best; return records. Only captured completed rounds count.
- `abandon(account, kind, operation_id)`: marks an operation abandoned; no refund,
  no record.
- Expose `records(account, kind)` → `{personal_best, world_best}`.
- On completion, call `TaskService.record(account, "activity_result",
  {"activity": kind, **result})` so tasks can react (Milestone 4 wires rewards).
- Close/abandon is triggered on activity close, disconnect, room change, or
  logout using existing `ActivityService.close*` paths.

### 3.4 Commands

Register in `server/commands/core.py`:
- `.lazor_start <operation_id>` — starts a Lazor Rush round for the account's
  open `lazor-rush` activity; delegates to `ActivityResultService.start`.
- `.activity_records lazor-rush` — returns personal and world records.
`.play molly` continues to open the activity; opening is free, Start costs Energy.

### 3.5 Lazor Rush engine (`activities/lazor-rush/`)

Replace the redirect stub with `index.html`, `lazor-rush.js`, `lazor-rush.css`
(and split further if needed). Requirements:
- Canvas-based; explicit **Start** / **Play Again**; before Start, Molly and the
  laser are visibly separated so a round cannot begin with an immediate capture.
- Round begins by posting `.lazor_start <operation_id>` through the bridge; the
  round only runs on an approved result.
- Continuous acceleration: Molly's speed increases over the round; the timer
  measures survival time.
- Laser follows the pointer inside the play area, or the finger while touching
  and dragging; when the pointer leaves or the finger lifts, the laser stays at
  its last valid position and Molly keeps chasing it.
- Capture when Molly's **visible body** reaches the laser, with no oversized
  invisible hitbox.
- No pause when minimized or covered: the game loop keeps running; the host must
  not throttle rAF for gameplay (the browser test fixture's throttle is
  test-only).
- On capture, post `TinyActivity.result({operationId, result: {seconds, captured:true}})`
  and display the server-returned survival time and records.
- Abandoning (Close, room change, disconnect) ends the round without a record or
  refund.
- Match `activities/shop/` conventions for layout, the shared bridge, and audio
  hooks; keep files under 1200 lines and playable on touch.

## 4. Tests

Create `tests/test_milestone3_activities.py` (subclass
`tests/test_milestone2_integration.py:Milestone2IntegrationTestCase`) plus
service tests. Cover:
- Start cost charged exactly once per `operation_id`; insufficient Energy
  rejects; Tired blocks a second start but not an already-paid round.
- Completed captured round records personal/world best; uncaptured or abandoned
  rounds do not.
- Replay of a result `operation_id` does not re-record or re-reward.
- Tampered signature and replayed/mismatched tokens are rejected with no state.
- Records separate per user and shared across the world.
- `activity_result` task trigger fires on completion.
Add browser flows for mouse and touch play, and minimized/covered states. Add
visual captures; review baselines manually.

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] Results are signed and validated server-side; tampering/replay changes nothing.
- [ ] A paid round continues even if the cost makes the user Tired.
- [ ] Only captured completed rounds count toward records.
- [ ] Disconnect/close abandons without refund.
- [ ] Lazor Rush is playable with mouse and touch and keeps running minimized/covered.
- [ ] Every file under 1200 lines; existing tests pass.

## 6. Guardrails

- Do **not** trust client-reported time or capture; validate the signed result.
- Do **not** hard-code tutorial reward amounts; expose the task trigger only.
- Do **not** pause gameplay when the window is minimized or covered.
- Do **not** refund an abandoned round.
