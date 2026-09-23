# Milestone 3 — Phase E: Room-Owner Editing

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A–D must be complete (`OwnershipService`,
> `EnvironmentService`, powers, and the behavior runtime all exist).

## 1. What this phase delivers

The in-game `Edit Room` core card, activated only for a room owner or an
authorized editor. Owners can add/remove/move/rotate/scale **approved decorative
props**, change **approved visual environment settings only**, keep a local draft
with a base revision, submit one validated `Save layout` patch, and recover from
stale revisions — without ever creating value or changing gameplay.

Out of scope: the standalone World Editor and Card Database (F), activity hooks
and Lazor Rush (G). Room cards continue through normal drop/pickup/pin commands;
the editor never duplicates them.

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` sections *Room Editing*, *Room Ownership*,
  *Props*, *The Room View*.
- `doc/milestone-3.md` work package 5.
- `server/content/worlds.py` — `PropDefinition`, `PropInstanceDefinition`,
  `RoomDefinition`; add the approval flag and environment whitelist.
- `server/state/world_state.py` — `room_states.props_json`, `layout_revision`.
- `server/services/rooms.py` — `build_snapshot`, `_serialize_prop`, navigation.
- `server/services/ownership.py` (Phase C) — `can_edit`, `owner_of`.
- `server/services/powers.py` (Phase D) — `has_power`.
- `server/services/environment.py` (Phase C) — environment gating.
- `server/behaviors/dispatcher.py` (Phase A) — `on_quick_action` for authored
  prop actions.
- `server/commands/core.py`, `server/commands/outcomes.py`, `server/app.py`
  (`RoomService` construction, WS loop), `server/security.py` (CSRF helpers).
- `app/js/views/edit-room-view.js` — current locked stub.
- `app/js/board.js`, `app/js/board-helpers.js`, `app/js/drag.js`,
  `app/js/prop-viewer.js`, `app/js/views/view-helpers.js`, `app/js/ui.js`,
  `app/js/cards.js`, `app/js/state.js`, `app/css/main.css`, `app/css/cards.css`.

### Hard rules
- Every source file **under 1200 lines**; split editor modules if needed.
- Python: `from __future__ import annotations`, type hints, docstrings on public
  functions, **no inline comments** except one or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- Reuse the live Three.js room component (`app/js/board.js`); do **not** build a
  second renderer.
- Server verifies prop approval, transform bounds, instance IDs, ownership, and
  the environment whitelist before committing. Client-side checks are UX only.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Data model (no schema-version bump)

Phase C added `room_states.environment_json` and `room_states.layout_revision`.
Live prop layout lives in `room_states.props_json` (default `'{}'`). Add to
`WorldStateRepository`:
- `read_room_layout(room_id) -> dict` returning `{"revision": int, "props": [...]}`.
- `write_room_layout(connection, room_id, props, *, expected_revision) -> int`
  doing a compare-and-swap on `layout_revision`; raise a revision-conflict error
  when `expected_revision` does not match.
Seed `props_json` from the YAML prop list on room initialization (only when the
room is uninitialized, alongside existing card seeding).

### 3.2 Content approval flags

Extend `props/props.yaml` validation in `server/content/worlds.py`:
- `editable: bool` on prop definitions (default `False`). Only `editable` props
  may appear in the decorative library.
- `editor_scale_min` / `editor_scale_max` (optional floats, defaults 0.25/4.0).
- Room YAML `editor.environment` whitelist: a list of allowed visual keys,
  restricted to `palette` and `board_image_style`. Never allow `dark`, auras, or
  gameplay values.
- Validate that an `editable` prop is also `decorative`; reject gameplay props
  marked editable.

### 3.3 Layout service

Create `server/services/room_layout.py` — `RoomLayoutService(hub, world,
world_state, ownership, environment)`:
- `view(account, room_id) -> dict`: `{room_id, revision, can_edit, props:
  [instance], library: [approved prop definitions], environment_whitelist,
  environment}`. `can_edit` uses `ownership.can_edit`.
- `save(account, room_id, base_revision, patch) -> LayoutUpdate`:
  - Require `can_edit`; reject unauthorized gameplay edits.
  - Validate every instance: known approved `prop_id`; `custom:<uuid>` IDs are
    well-formed; unique IDs; position `x,y in [0,100]`, `z in [0,50]`; rotation
    normalized to `[0, 360)`; scale within `editor_scale_min/max`; no removal of
    non-editable props.
  - Validate the environment patch against the room whitelist only.
  - Commit props + environment + `layout_revision` in one transaction with the
    compare-and-swap; a stale `base_revision` raises revision conflict.
  - Return the new revision and a `{"type":"room.layout.updated", "room_id",
    "revision", "props", "environment"}` event.
- `effective_props(room_id) -> list[PropInstanceDefinition]` merging base YAML
  instances with live overrides, used by `RoomService.build_snapshot`.

### 3.4 Endpoints and commands

- Add `GET /api/rooms/{room_id}/layout` (session auth) returning `view`.
- Add `POST /api/rooms/{room_id}/layout` (session + Origin + CSRF, same checks as
  `_enforce_authenticated_post`) taking `{base_revision, patch}` and returning
  the new layout; stale revision returns HTTP 409 with the current layout for
  reload/reapply. Use HTTP rather than a WS command because layout patches can
  exceed `MAX_COMMAND_SIZE` (`server/protocol.py`).
- Register `.room_layout` for a quick read (payload = view) if useful for the
  client, delegating to the same service.
- `RoomService.build_snapshot` uses `effective_props` and includes
  `"layout_revision"` and `"can_edit_room"`.
- Broadcast `room.layout.updated` to the room after a successful save (use the
  existing broadcast helper in `server/app.py`).

### 3.5 Client

Implement the full editor in `app/js/views/edit-room-view.js` plus split modules
under `app/js/editing/` (for example `edit-store.js`, `gizmo.js`,
`prop-library.js`), all under 1200 lines:
- **Permission**: owners/authorized editors see the editor; others keep the
  locked message.
- **Library**: list approved decorative props with thumbnails/labels; add on
  click or drag to the board.
- **Selection and transforms**: ray-cast selection reusing `board.js`; visible
  move/rotate/scale gizmos; mouse and touch drag; keyboard arrow keys nudge,
  `[`/`]` rotate, `+`/`-` scale; snap toggles (position grid and 15° rotation).
- **Undo / cancel**: an undo stack of layout snapshots; `Escape` cancels the
  active transform first, then an unsaved editor close prompts confirmation.
- **Draft**: keep a local draft plus `base_revision`; mark the editor dirty when
  it diverges; `Save layout` POSTs one patch.
- **Conflict/failure**: on HTTP 409 offer reload/reapply using the returned
  layout; on other errors preserve the draft and show the error; never discard
  the user's work silently.
- **Environment**: expose only whitelisted visual settings; never expose auras.
- Wire `Edit Room` core-card availability from `can_edit_room` in bootstrap so
  unauthorized users get the locked state.
- Add CSS to `app/css/cards.css`/`app/css/main.css` in the existing style; do not
  build a separate visual language.

## 4. Tests

Create `tests/test_milestone3_room_editing.py` (subclass
`tests/common.py:ServiceTestCase`, plus integration coverage through the HTTP
endpoints using `tests/test_milestone1.py:RuntimeTestCase`). Cover:
- Transform validation: bounds, scale limits, rotation normalization, invalid
  instance IDs, and removal of non-editable props are rejected atomically.
- Stale `base_revision` conflict returns the current layout and commits nothing.
- Unauthorized gameplay edits (auras, `dark`, non-approved props) are rejected.
- Owner and builder/editor can edit; unrelated users cannot.
- Atomic save: a failure leaves the previous layout intact.
- Undo/cancel round-trips in the client store (unit test the store module).
Add a browser flow to `tests/browser/flows.spec.js` covering mouse, touch,
keyboard, snap, undo, a revision conflict, and a successful save visible to a
second client. Add visual captures to `tests/browser/screenshots.spec.js` for
the editor (review baselines manually before committing).

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] Only owners/authorized editors can open the editor.
- [ ] Adds/moves/rotates/scales commit only through one validated atomic patch.
- [ ] Stale revisions are rejected with a reload/reapply path.
- [ ] Unsaved work is never silently discarded.
- [ ] Gameplay values and auras are never editable.
- [ ] Every file under 1200 lines; existing tests pass.

## 6. Guardrails

- Do **not** create or duplicate room cards from the editor; use normal drop/pickup.
- Do **not** expose or persist any gameplay aura/environment through the whitelist.
- Do **not** trust client transforms; revalidate every value server-side.
- Do **not** maintain a second Three.js renderer for editing.
