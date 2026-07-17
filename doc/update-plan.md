# Tinyrooms Spec Alignment Update Plan

## Scope and source of truth

This plan compares:
- `doc/app.md`
- `doc/room.md`

against the current implementation in:
- server: `tinyrooms/`
- client: `app/`

and defines a staged implementation plan to align the codebase with the specification.

---

## 1) Current state vs. specification (gap analysis)

## 1.1 Client structure (major mismatch)

### Spec expects (`doc/app.md`)
- `mainPage` with:
  - `statusPanel`
  - `logPanel`
  - `activityPanel`
  - `roomPanel` (`roomHeader`, `roomCanvas`, `roomExits`)
  - `actionsPanel` (`lookBox`, `actionPalette`)

### Current implementation
- `app/client.html` currently has:
  - `statusDisplay`
  - `messages`
  - message input row (`msgInput`, `sendBtn`, `actionsChips`)
  - `actionsContainer` with `descriptionPanel` and `actionButtons`
  - no `roomPanel`, `roomHeader`, `roomCanvas`, `roomExits`, `activityPanel`, or `lookBox`.

### Impact
- The DOM/CSS/JS architecture is not aligned with the target UI model and must be refactored before feature parity work.

## 1.2 Room rendering model (major mismatch)

### Spec expects (`doc/room.md`)
- Stage/canvas-based room view:
  - background + props on stage
  - movable foreground peeps/objects as sprites
  - drag/drop movement
  - smooth movement updates

### Current implementation
- `app/client.js` uses a generic `update_view` renderer with:
  - room image
  - text label/description
  - icon strip (`.icon-strip`) of 64x64 icons
- no canvas rendering pipeline, no sprite layering, no drag/drop movement system.

### Impact
- Client rendering must move from static “view card + icon strip” to dedicated room stage renderer.

## 1.3 Room update protocol (major mismatch)

### Spec expects (`doc/room.md`)
- `update_view` messages with view values:
  - `header`
  - `room-stage`
  - `room-object` (single entity deltas, smooth move)
  - `room-exits`

### Current implementation
- server `tinyrooms/room.py::send_view()` emits only:
  - `view: "main"` with full payload (`label`, `description`, `image`, `icons`)
- client has no handlers specialized for the spec view types.

### Impact
- Server and client message contracts need redesign to support partial updates and incremental object movement.

## 1.4 Data model gaps: props/sprites/positions

### Spec expects (`doc/room.md`)
- rooms contain props (owner-editable only by room owner)
- props have icon/img/sprite forms
- objects and peeps rendered as moving sprites on stage

### Current implementation
- `tinyrooms/Room` has `objs` and `peeps`, but no dedicated `props` model.
- objects currently rely on icon preprocessing (`tinyrooms/icons.py`) and icon-strip serialization.
- no persisted x/y positions or orientation for objects/peeps/props.
- no room-owner authorization flow for prop editing (even though `owner_id` field exists).

### Impact
- World definitions, runtime models, and worldstate DB schema require expansion.

## 1.5 Actions panel behavior mismatch

### Spec expects (`doc/app.md`)
- six-slot action palette with specific default actions:
  - Look, Use/Interact/Talk, Emote, Equip, Self, Extras
- palette can switch sets (e.g., Emote set with Back)

### Current implementation
- action buttons are generated directly from server `actions_def` groups in `client.js`.
- no fixed six-action palette semantics; no activity-type panel switching model per spec.

### Impact
- UI command model must be layered: a stable client-side palette UX above server-defined actions.

---

## 2) Target architecture (design decisions)

## 2.1 Backward-compatible transition strategy

1. Keep existing socket events (`update_view`, `actions_def`, etc.).
2. Introduce new `update_view.view` values from spec.
3. Migrate client to new panelized DOM and handlers.

## 2.2 New canonical room view data contract

Define structured payloads:

- `view: "header"`
  - room id, label, short description, status indicators, owner flags.

- `view: "room-stage"`
  - stage background
  - full prop list with stable ids, sprite, x/y, orientation, z-index/layer
  - optional stage metadata (width/height, theme, bounds)

- `view: "room-object"`
  - upsert/remove one foreground entity (object/peep)
  - includes movement target x/y and animation hints
  - delta-friendly for smooth movement

- `view: "room-exits"`
  - normalized exit definitions for room buttons

This should become the canonical contract for room UI state.

## 2.3 Room entity model separation

Split entities into:
- **Props**: part of fixed stage, owner-editable
- **Foreground entities**: movable peeps and objects

This avoids overloading the current icon-only abstraction and aligns with spec semantics.

## 2.4 Rendering model

- Use `roomCanvas` as the stage viewport.
- Render background + props at fixed positions.
- Render foreground sprites as independent positioned elements (or canvas layers) with CSS shadow for separation (per spec).
- Apply movement interpolation for `room-object` updates.

## 2.5 Permission model for prop editing

- Enforce room owner checks server-side using `room.owner_id`.
- Add explicit failure messages on unauthorized modifications.
- Do not rely on client-only gating.

---

## 3) Implementation plan (phased)

## Phase 0 — Preparation and schema design

1. Define new payload schemas in code comments/types (server + client).
2. Design worldstate schema migration for:
   - room props (id, room_id, prop_type, sprite/icon/img refs, x, y, orientation, layer, metadata)
   - foreground position state for objects/peeps where required.
3. Add migration-safe DB init logic in `tinyrooms/db.py` (non-destructive, additive columns/tables).

Deliverable: approved schema + message contract docs in code.

## Phase 1 — Server room model and serializers

1. Extend `Room` (`tinyrooms/room.py`) to include:
   - prop container
   - helper methods to serialize header/stage/object/exits views.
2. Extend world loading (`tinyrooms/world.py`) to parse props from room definitions.
3. Add/extend serializers (likely `tinyrooms/icons.py` replacement/extension) for icon/img/sprite fields.
4. Replace monolithic `send_view()` with granular emit methods:
   - `send_header_view(user)`
   - `send_room_stage_view(user)`
   - `send_room_exits_view(user)`
   - `send_room_object_update(user|room broadcast, entity, change_type)`
5. Update room join/leave flow to emit spec views in the correct order.

Deliverable: server emits spec-aligned updates while still optionally supporting legacy `main`.

## Phase 2 — Client DOM/CSS refactor to panel model

1. Refactor `app/client.html` into spec panel hierarchy.
2. Update CSS (`app/client.css` + skins as needed) for:
   - room panel layout
   - canvas/stage sizing rules
   - foreground shadow styling
   - action palette six-slot behavior.
3. Keep existing non-room features (login, chat log, connection indicator) functional.

Deliverable: panelized UI structure matching `doc/app.md`.

## Phase 3 — Client room renderer and update handlers

1. Replace generic `main` renderer in `app/client.js` with dedicated handlers:
   - `handleHeaderUpdate`
   - `handleRoomStageUpdate`
   - `handleRoomObjectUpdate`
   - `handleRoomExitsUpdate`
2. Build stage renderer in `roomCanvas`:
   - background + props as stage layer
   - object/peep sprites as foreground entities
   - smooth movement transitions for existing entities.
3. Add drag/drop interaction:
   - user peep draggable by owner user
   - room objects draggable per game rules
   - props draggable/editable only when server reports owner capability.
4. Emit movement/edit intents to server via explicit socket messages (new event names to define).

Deliverable: interactive room stage with synchronized movement behavior.

## Phase 4 — Action palette and activity panel alignment

1. Introduce fixed six-button action palette UI in `actionsPanel`.
2. Map palette actions to existing/extended action system:
   - Look
   - Use/Interact/Talk
   - Emote (swap set + Back)
   - Equip
   - Self
   - Extras
3. Implement `activityPanel` modes and routing:
   - Equip
   - Look
   - Self
   - Dialog
4. Integrate `lookBox` one-line quick description behavior.

Deliverable: UX behavior aligned with `doc/app.md` while preserving server compatibility.

## Phase 5 — Cleanup, compatibility removal, and hardening

1. Remove deprecated `view: "main"` flow once spec flow is stable.
2. Remove icon-strip-only assumptions from client/server.
3. Ensure room-owner permission checks are consistently enforced server-side.
4. Validate reconnect/login/join-room flows with new UI state reset rules.

Deliverable: final spec-oriented architecture without temporary compatibility code.

---

## 4) Suggested file-level worklist

### Server (`tinyrooms/`)
- `room.py`: room data model, emit methods, user/object sync behavior.
- `world.py`: load props/sprite metadata from world definitions.
- `db.py`: worldstate schema expansion + read/write functions.
- `connection.py`: socket handlers for new movement/prop-edit events.
- `actions.py` / `message.py`: integrate action palette routing and exit/object targeting semantics if needed.
- `icons.py`: likely generalize beyond icon-only to icon/img/sprite metadata utilities.
- `object.py`, `peep.py`: add transform/position fields and serializer helpers.

### Client (`app/`)
- `client.html`: panel structure rebuild.
- `client.css` (+ theme CSS files): panel and stage styling.
- `client.js`: `update_view` protocol handlers, room stage state machine, drag/drop, animation.
- `ui.js`: action palette + activity panel behaviors (may split into modules if code grows).
- `state.js`: persist selected UI state relevant to new panels if needed.

### Data (`data/worlds/home/`)
- `rooms/rooms.yaml`: add prop definitions and room stage metadata.
- `things/things.yaml`: standardize icon/img/sprite fields for objects.

---


## 7) Implementation Details

**Canvas technology:**  `roomCanvas` should use the DOM directly rather than an HTML canvas, so all elements can be controller directly.
**Coordinate system and scaling:** All elements are placed using pixel pased coordinates. The room stage canvas is always 256x512 pixels, but it can be rescaled for display on smaller clients.
**Movement authority:** When a user drags/drops an object or its character, the change is only sent AFTER the item is dropped. During drag/drop, the user drags a transparent copy of the sprite it is moving.
**Peep movement permissions:** Should users only move their own peep, but a room owner can move any entity inside an owner room.
**Prop definitions:** props should live in a new YAML namespace/file (e.g., `props/props.yaml`) 
**Display assets:** Are `icon`, `img`, and `sprite` can fallback to one another when left unspecified. Only img is mandatory.
**Sprite size policy:** Spec mentions ranges (32–64 for sprite, max 128 for img). Server should enforce normalization/resizing (like current icon preprocessing).
**Layering/z-order:** A user's character is always displayed on top of all other objects on the user client. Except for this, display order of objects is based on last thing moved goes to front. Of course room background and props remain behind any objects.
**Room exits UI:** Room exits are exclusively button-based in `roomExits`.
**Action palette mapping:** Palette actions map to existing YAML action IDs (e.g., `basic.look`), Add new action definitions as needed to follow the new spec. Current test actions / emotes can be excluded from display at this point.
**Activity panel content source:** Equip/Self/Dialog panel payloads will be sent as dedicated socket events, separate from `update_view` with new view names?
**Backward compatibility window:** No need to maintain a temporary legacy mode (`view: "main"`), aggressively remove any unised code in both client and server.

