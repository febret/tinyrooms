# Milestone 3 — Phase F: World Editor and Card Database

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A–E must be complete. This is the largest phase;
> split every module so no file reaches 1200 lines.

## 1. What this phase delivers

Two separate web applications served by the same backend:
1. **World Editor** at `/world-editor` — a server-side draft copied from the
   published definition revision, with a full visual editing surface (rooms,
   board art/settings, props, initial room cards, exits, NPC placement, dialogs,
   activities, environment/gameplay settings, ownership defaults), validation
   panel, undo/redo, dirty markers, Save Draft, Discard, preview, and Publish.
2. **Card Database** at `/card-database` — a read-only catalog of shared/world
   definitions, artwork, source scope, type, rarity, generated details, packs,
   recipes, and reference/validation errors.

Publishing validates the whole content graph, writes files atomically, records a
revision/backup, and reconciles live state without resetting user progress.

Out of scope: activity result hooks and Lazor Rush (G).

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` sections *World Editor*, *Worlds*, *Props*,
  *Rooms*, *Peeps*, *Activities*.
- `doc/milestone-3.md` work package 6.
- `server/content/worlds.py`, `server/content/cards.py`,
  `server/content/gameplay.py`, `server/content/tasks.py` (Phase B),
  `server/content/recipes.py` (Phase C) — the validators Publish must reuse.
- `server/content/common.py` — `ContentError`, `load_yaml_file`.
- `server/state/world_state.py`, `server/state/migrations.py`.
- `server/services/ownership.py` (C), `server/services/environment.py` (C),
  `server/services/powers.py` (D), `server/services/audit.py` (D).
- `server/config.py` — feature flags, paths.
- `server/app.py` — `create_runtime`, `RuntimeState`, static routes.
- `app/index.html`, `app/js/board.js`, `app/js/board-helpers.js`,
  `app/js/prop-viewer.js` — the live Three.js room component to reuse.
- `app/css/main.css` — the existing visual language.
- `.local/` — gitignored runtime directory for drafts/backups.

### Hard rules
- Every source file **under 1200 lines**; split aggressively.
- Python: `from __future__ import annotations`, type hints, docstrings on public
  functions, **no inline comments** except one or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- No `localStorage`/`sessionStorage`; drafts live on the server.
- Never edit world YAML by hand; Publish validates through the loaders and writes
  atomically.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Schema and config

Bump **world** schema 8 → 9:

```sql
ALTER TABLE room_cards ADD COLUMN placed_by_account_id TEXT;
CREATE TABLE IF NOT EXISTS world_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Add `placed_by_account_id` to `_ROOM_CARDS_COLUMNS`, update `add_room_card` and
`take_room_card` in `server/state/world_state.py` and the drop path in
`server/services/cards.py` to record the dropping account (YAML seeds stay
`NULL`). Update `_WORLD_MIGRATIONS[9]`.

`server/config.py`:
- Add `world-editor` and `card-database` to the known feature set.
- Add `drafts_path = repo_root/".local"/"drafts"` and
  `revisions_path = repo_root/".local"/"revisions"` to `AppConfig`, creating the
  directories at load.

### 3.2 Draft model

Create `server/services/world_editor.py` — `WorldEditorService(...)`:
- A draft is a JSON object containing the full editable content graph:
  world metadata; rooms (art, style, palette, dark, environment whitelist,
  exits, initial cards, prop instances); props/propsets; peeps (image, script
  reference, actions, dialog); tasks; recipes; activities; powers; ownership
  defaults. It mirrors the YAML schema so Publish can serialize it back.
- `load_draft() -> dict`: return the saved draft under
  `drafts_path/<world_id>.json`; if absent, build a draft from the published
  files.
- `save_draft(draft) -> DraftInfo`: structural validation only (shape, unique
  IDs, known reference targets); atomic write (temp file + `os.replace`); bump
  `draft_revision`; never touch the running world.
- `discard_draft()`: delete the draft file; the next `load_draft` rebuilds from
  published files.
- `validate(draft) -> ValidationReport`: serialize the draft to each YAML file
  in a temp directory, run the real loaders (`load_card_catalog`,
  `load_world_definition`, `load_task_definitions`, `load_recipes`, gameplay
  loaders), and collect all errors with field paths. Also report reference and
  validation errors for the Card Database.
- `publish(draft, *, confirmations) -> PublishResult`:
  - Fail if `validate` reports errors.
  - Require explicit confirmations for destructive changes (deleted rooms,
    removed exits, removed props holding live cards).
  - Write all YAML files atomically: stage into a temp directory, back up the
    current files, then move the staged files into `worlds/<world>/` with
    `os.replace`. Record `revisions_path/<world_id>/<revision>/` containing the
    prior files and a manifest, and write `world_meta['published_revision']`.
  - Reconcile live state (see 3.3), then request a runtime world reload.
  - Audit the publish with actor, revision, and result.

### 3.3 Live-state reconciliation

Create `server/services/world_reconcile.py` or add methods to
`WorldEditorService`:
- Reload the published content into a fresh `WorldDefinition`/catalogs.
- Preserve user inventories, `task_progress`, `memories`, ownership, and reward
  ledgers (untouched — they live in the profile DB).
- Preserve room cards in rooms that still exist; re-seed rooms whose definitions
  changed only when they were uninitialized.
- Deleted rooms: for each live `room_cards` stack with
  `placed_by_account_id` not null, return those cards to the dropper's inventory;
  seed stacks are discarded only after confirmation. Move occupants of a deleted
  room to the configured fallback room (default the entry room) and update
  `remembered_room`.
- Deleted props: reject the publish if a deleted prop instance still holds
  environment state or live behavior state, unless confirmed.
- Broadcast a reload notice and refresh snapshots for connected users
  (`room.layout.updated` or a dedicated `world.reloaded` event; reconnect
  snapshots remain the recovery mechanism).
- Implement `RuntimeState.reload_world()` in `server/app.py` so the running
  process swaps `world`, catalog, recipes, tasks, and task definitions, then
  re-runs reconciliation. Serialize reloads and publishes through a single
  asyncio lock (the world-level mutation lock).

### 3.4 Routes and authorization

- Gate `/world-editor` behind the `world-editor` feature and `builder` or
  `game-master` power. Gate `/card-database` behind the `card-database` feature
  and `builder`/`game-master` power (read-only).
- Add JSON API routes (all session-auth; write routes also Origin + CSRF via
  `_enforce_authenticated_post`):
  - `GET /api/world-editor/draft`
  - `PUT /api/world-editor/draft`
  - `POST /api/world-editor/discard`
  - `POST /api/world-editor/validate`
  - `POST /api/world-editor/publish`
  - `GET /api/card-database`
- Audit every publish and failed authorization.

### 3.5 World Editor UI (`world-editor/`)

A standalone ES-module app served by new static routes
(`/world-editor/`, `/world-editor/{path}`), reusing the live room renderer via
absolute imports (`/app/js/board.js`, `/app/js/board-helpers.js`,
`/app/js/prop-viewer.js`) and the existing CSS vocabulary. Required surfaces
(split into modules; keep every file under 1200 lines):
- **Room list/search** with dirty markers and add/delete room.
- **Room canvas**: the Three.js board with prop placement/selection and
  transforms; a properties panel for board art/style/palette/dark and initial
  room cards.
- **World-map graph**: a 2D graph of rooms and exits with add/edit/delete exit.
- **Properties panel**: contextual fields for the selected entity.
- **Prop library**: shared + world props; place instances.
- **NPC/dialog editor**: peep placement plus a dialog-tree editor with node IDs,
  text, choices, conditions, script callbacks, and side effects.
- **Tasks/recipes/environment/ownership editors** matching the server schemas.
- **Validation panel**: show `validate` errors with field paths.
- **Undo/redo** history and dirty state.
- **Toolbar**: Save Draft, Discard (with confirmation), Preview (render the
  draft's room without publishing), Publish (with destructive confirmations).
The UI must remain operable on portrait/mobile (responsive panels) and without
hover.

### 3.6 Card Database UI (`card-database/`)

A read-only responsive app served at `/card-database/`. Show, for shared and
world cards: front art, name/description, source scope (`base`/world), type,
rarity, generated details (bonuses/effects), owning packs, recipes that use the
card, and reference/validation errors. Never expose inventory or grant actions.
Support desktop and portrait layouts.

## 4. Tests

Create `tests/test_milestone3_world_editor.py` (subclass
`tests/common.py:ServiceTestCase`; use `RuntimeTestCase` for HTTP routes). Cover:
- Draft isolation: saving a draft never mutates the running world.
- Invalid publish: validation errors block publish and leave files untouched.
- Destructive confirmation: deleting a room without confirmation is rejected;
  with confirmation it moves occupants to the fallback room and returns
  user-placed cards to their droppers.
- Backup: the prior revision is recorded under `revisions_path`; publish is
  atomic on a simulated write failure.
- Live-state reconciliation: inventories, task progress, ownership, and unrelated
  room cards survive a publish.
- Card Database payload includes packs/recipes/reference errors and is read-only.
Add browser flows to `tests/browser/flows.spec.js` for draft/preview/publish and
the Card Database responsive views. Add visual captures in
`tests/browser/screenshots.spec.js`; review baselines manually.

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] `/world-editor` and `/card-database` require the feature + proper power.
- [ ] Save Draft never changes the live world; Publish validates the real loaders.
- [ ] Publish is atomic, backed up, and revision-recorded.
- [ ] Reconciliation preserves user progress and never silently deletes possessions.
- [ ] Both surfaces reuse the live Three.js room component.
- [ ] Every file under 1200 lines; existing tests pass.

## 6. Guardrails

- Do **not** mutate the live world from Save Draft.
- Do **not** write YAML before full validation succeeds.
- Do **not** let the Card Database edit inventory or grant cards.
- Do **not** build a second 3D renderer.
- Do **not** expose draft/revision paths through static asset routes.
