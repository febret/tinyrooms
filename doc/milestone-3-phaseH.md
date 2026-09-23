# Milestone 3 — Phase H: Seed Authoring World, Milestone 5 Doc, and Review

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A–G must be complete. This is the final Milestone
> 3 phase.

## 1. What this phase delivers

1. A small **seed authoring world** (`worlds/authoring/`) that exercises every
   reusable Milestone 3 system using only definitions plus a trusted script — the
   artifact for the manual review gate.
2. **`doc/milestone-5.md`**, a complete milestone specification for cross-world
   support and travel (deferred from Milestone 3) describing a simple two-world
   tutorial setup derived from the tutorial world.
3. Updated project documentation (`doc/architecture.md`, `doc/db.md`,
   `AGENTS.md`, `README.md`) for all Milestone 3 systems.
4. A final full-suite pass and a manual review checklist.

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` (all sections referenced by Milestone 3),
  `doc/milestone-3.md` (definition of done and manual review gate),
  `doc/milestone-4.md`, `doc/planning-hints.md`.
- `worlds/tutorial/` — the reference content layout and asset set to copy from.
- `server/content/worlds.py`, `server/content/cards.py`,
  `server/content/tasks.py`, `server/content/recipes.py`, `server/content/gameplay.py`.
- `server/behaviors/*` — the typed script API the seed world's script must use.
- `doc/db.md` and `doc/architecture.md` — update both.
- `tests/common.py`, `tests/test_ui_presentation.py`, `tools/seed_review_account.py`.

### Hard rules
- Every source file **under 1200 lines** (including new content YAML does not
  count toward the source limit, but scripts do).
- Python: `from __future__ import annotations`, type hints, docstrings, no
  gratuitous comments.
- Never add secrets. Never edit checked-in visual baselines to mask bugs.
- Tests: `python -m unittest discover -s tests -v`, then `npm run test:browser`.

## 3. Work

### 3.1 Seed authoring world (`worlds/authoring/`)

Create a compact world (3–5 rooms) that demonstrates, through definitions and one
trusted script, every Milestone 3 system. Reuse existing assets by copying from
`worlds/tutorial/`; do not invent new art.

Required content:
- `world.yaml`: `id: authoring`, `entry_room`, label/description, palette, and a
  `powers:` map assigning `admin` and `builder` (and `realtor`, `moderator`,
  `game-master` to appropriate usernames) for review accounts.
- `rooms/rooms.yaml` with board images copied from the tutorial rooms plus:
  - a **dispenser** prop instance (`behavior: dispenser`, `content`, `cooldown`);
  - a **crafting station** prop instance with `recipes: [<recipe>]` and an
    `actions` entry opening `.craft @prop:<id>`;
  - an **aura** room with an `aura:` entry;
  - an **environment** room (`dark: true`) and a prop/script action that sets
    `lighting` to normal;
  - at least two **editable decorative** props (`editable: true`,
    `decorative: true`) and a room `editor.environment` whitelist for the
    room-edit review;
  - a **locked exit** requiring a card, and a normal exit.
- `props/props.yaml`: reuse/copy the tutorial prop definitions you need and copy
  their GLB models into `worlds/authoring/props/`.
- `peeps/peeps.yaml`: one scripted NPC with a small dialog tree and authored
  actions (`.talk`, `.act pet`). Add `peeps/guide.py` implementing `on_quick_action`
  and `on_dialog_action` with the typed `BehaviorContext` API (feedback, starting
  a dialog, applying a counter, starting a task).
- `cards/cards.yaml` and `cards/pack.yaml`: one or two world cards for the
  crafting recipe and a small pack; reuse base cards for emotes/skills.
- `recipes.yaml`: one recipe with two ingredients and one output.
- `tasks.yaml`: at least two tasks — a 3-step personal task with a Kudos reward
  and memory tags, and one shared task with explicit participants/credit — plus a
  step triggered by `activity_result`.
- Room initial cards that teach selection, pickup, and equipment.

Validate the world by pointing `TRSERVER_WORLD_PATH` at it and starting the
server; fix all loader errors before proceeding.

### 3.2 `doc/milestone-5.md`

Write a complete, self-contained milestone specification whose main objective is
**trusted cross-world travel**. It must include:
- **Outcome and safety boundary**: operator-installed trusted worlds only; no
  general world chooser; TLS verification stays enabled.
- **Configuration**: `TRSERVER_TRUSTED_WORLDS` (explicit list of trusted world
  origins/IDs) and optional `TRSERVER_TRUSTED_CA_FILE`; strict validation; no
  insecure fallback.
- **Transfer tickets**: short-lived, signed, single-use tickets bound to account,
  source world, destination world, optional destination room, profile revision,
  and expiry. Describe generation, storage, and replay rejection.
- **Handshake**: source validates exit/access/Energy but charges nothing and
  changes no loadout until the destination accepts. Destination validates trust,
  ticket, shared active-session generation, and entry access, then establishes
  the session and acknowledges. On success: charge the normal room-change Energy,
  revoke the old session, close activities/dialogs, remove source-native cards
  from equipment/skills, and load destination state. On failure the user is
  unchanged with no Energy cost.
- **Shared vs world-scoped boundaries**: reproduce the design's split (shared
  identity/sticker/friends/global cards/level/Kudos/Bops/Energy/Tired; world-
  scoped Health/Cleanliness/custom counters/buffs/Sick/Stinky/ownership/memories/
  tasks/native cards).
- **Two-world tutorial setup**: describe a second world derived from the tutorial
  world (for example `worlds/neighbor/`) with a cross-world exit/portal in the
  tutorial Garden leading to the neighbor world's entry room and back. Give the
  directory layout, which assets are copied vs. newly needed, the trust
  configuration, and the end-to-end acceptance scenarios (successful round trip,
  unavailable destination, untrusted destination, expired/replayed ticket,
  Energy charge and native-card loadout removal/recovery).
- **Work packages, required tests, data rules, and definition of done** in the
  same style as `doc/milestone-3.md`.
- Optionally scaffold `worlds/neighbor/` with the described YAML skeleton reusing
  tutorial assets (recommended so the setup is "included in the project").

### 3.3 Documentation updates

- `doc/architecture.md`: document the behavior runtime/event dispatcher, dialog
  subsystem, room tick, new services (tasks, memories, crafting, dispensers,
  environment, ownership, powers, audit, room layout, world editor, activity
  results), new protocol events (`room.environment`, `room.layout.updated`,
  `world.reloaded`, `activity.result`), new commands, powers, and the
  `/world-editor` and `/card-database` routes.
- `doc/db.md`: add every new table and column from Phases A–G with the same
  level of detail as the existing tables.
- `AGENTS.md`: add the new env vars (`TRSERVER_ADMINS`, optional
  `TRSERVER_TICK_SECONDS`, feature flags `world-editor`/`card-database`), note
  the two new apps, and correct or remove the stale `server/client/` and
  `tests/client/` references if those directories still do not exist.
- `README.md`: setup, configuration, run, editor, and test instructions for the
  new surfaces.

### 3.4 Content lint and review tooling

- Add a single content-lint entry point (for example
  `python -m tools.content_lint <world>`) that validates every world YAML,
  script reference, asset, exit, dialog, task trigger, reward, recipe, pack, and
  editor whitelist using the real loaders. Add a Python test that runs it against
  the tutorial and authoring worlds.
- Update `tools/seed_review_account.py` to seed a review account with powers,
  cards, skills, a friendship, and task/memory state for the review gate.

### 3.5 Final verification and review gate

Run the full suites and walk the manual review gate from `doc/milestone-3.md`:
1. Dialog pacing and action placement.
2. Journal readability and memory calendar behavior.
3. Room-owner editing precision on mouse and touch.
4. World Editor terminology, validation, preview, and publish confidence.
5. Behavior authoring clarity and error diagnostics.
6. Lazor Rush feel.
Record the review findings in the milestone notes and resolve feedback before
declaring Milestone 3 complete.

## 4. Tests

Add or extend tests:
- `tests/test_milestone3_content.py`: the tutorial and authoring worlds load; the
  content-lint entry point passes; the authoring world has a dispenser, crafting
  station, aura, environment, editable props, tasks, recipes, packs, and a
  scripted peep.
- Extend the browser suite with an authoring-world walkthrough covering dialogs,
  journal, crafting, dispenser cooldown, aura, environment, room editing, world
  editor publish, card database, and Lazor Rush. Add visual captures for every
  major view; review baselines manually before committing.
- Ensure `tests/test_ui_presentation.py` still passes (no file ≥ 1200 lines, no
  external URLs, no `localStorage`).

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
python -m tools.content_lint worlds/tutorial
python -m tools.content_lint worlds/authoring
```

Definition of done:
- [ ] The authoring world loads cleanly and exercises every Milestone 3 system.
- [ ] `doc/milestone-5.md` fully specifies cross-world travel and the two-world
      tutorial setup, in the same style as the other milestone docs.
- [ ] `doc/architecture.md` and `doc/db.md` describe all new systems accurately.
- [ ] Content lint passes for both worlds.
- [ ] All Python and browser suites pass; no file reaches 1200 lines.
- [ ] The manual review gate is completed and feedback addressed.

## 6. Guardrails

- Do **not** invent tutorial storylines; the seed world demonstrates systems only
  and is not the Milestone 4 tutorial.
- Do **not** modify `doc/milestone-3.md` or checked-in baselines to make tests pass.
- Do **not** add new engine capabilities here; if one is missing, implement it in
  the appropriate earlier phase and its tests.
- Do **not** expose draft/revision/secret paths through static routes.
