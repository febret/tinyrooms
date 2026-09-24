# Milestone 3 - Behaviors, Dialogs, Editing, Journal, and Tasks

## Outcome

Make Tinyrooms an extensible sandbox. Trusted world authors can attach Python
behavior scripts to props and NPCs, author declarative dialogs and tasks, edit
and publish worlds, and grant room owners constrained decoration tools. Users
can complete tasks, collect and manage memories, craft, interact with
dispensers, and travel between explicitly trusted cooperating worlds.

This milestone delivers reusable systems and editor workflows. Milestone 4 uses
them to build and tune the complete tutorial.

## Inputs and safety boundary

- Milestones 1 and 2 are complete and their schemas/protocols are migrated, not
  replaced.
- Read [design.md](./design.md) sections Room Design through Commands and
  Administration and revisit Activities and Card Actions.
- World definitions and behavior scripts are operator-installed trusted code.
  They are **not** user-submitted sandboxed code.
- Ordinary room owners never gain behavior/script, reward, recipe, currency,
  aura, or arbitrary asset authoring rights.

Prototype guidance:

- Reuse the per-instance behavior namespace and event concepts documented in
  [peep.md](../attic/tinyrooms-prototype/doc/peep.md), but use an explicit,
  typed context API instead of injecting unrestricted runtime objects.
- Reuse validation/atomic-write ideas from
  [world_editor_api.py](../attic/tinyrooms-prototype/tinyrooms/world_editor_api.py)
  and visual-editor concepts from
  [world.md](../attic/tinyrooms-prototype/doc/world.md).
- Reuse crafting's validate-before-consume flow from
  [crafting.py](../attic/tinyrooms-prototype/tinyrooms/crafting.py), while
  implementing the current stack-selection, costs, and transaction rules.
- Do not copy prototype local imports, broad exception handling, direct live
  mutation, or save-immediately editor behavior. The current World Editor uses
  draft plus explicit Publish.

## Work packages

### 1. Behavior runtime and event dispatcher

Create a behavior subsystem with:

- Definition-time discovery of a Python file beside each peep YAML or referenced
  by an interactive prop definition.
- One loaded module per script and one explicit persisted state namespace per
  instance where needed. Script source is trusted; state must remain serializable.
- Typed events: `on_tick`, `on_enter`, `on_leave`, `on_quick_action`,
  `on_card_play`, `on_dialog_action`, and `on_activity_result`.
- A narrow `BehaviorContext` exposing actor, target, room/world read models and
  explicit methods such as emit feedback, mutate prop state, apply counter/
  buff changes, grant through reward ledger, start dialog/activity/task, update
  task progress, and request movement.
- Event dispatch after the initiating command has passed core validation.
  Script-requested mutations are validated again by domain services.
- Per-room ticks at a configurable default of one second. Skip offline users.
  Prevent overlapping ticks for one room and record slow/erroring handlers.
- An error in one script surfaces to operators and rejects only the affected
  action where applicable; it must not stop the room loop or partially commit.
- Script reload only through explicit world publish/reload, never on arbitrary
  filesystem changes in production.

### 2. Declarative dialogs

- Validate dialog trees embedded in peep YAML: stable node IDs, text, choices,
  destination/end, optional visibility conditions, script callback, and side
  effects.
- Detect dangling nodes and unreachable accidental nodes at load/publish time.
- Store active dialog per user with peep ID, current node, revision, and optional
  dialog state. A user may have one active dialog.
- Display text in the Look Bar and choices in Quick Actions. Provide a yellow
  Exit Conversation action.
- Revalidate peep presence, node, conditions, and permissions on every choice.
  Leaving the room, peep removal, logout, or world transfer ends the dialog.
- Side effects and next-node transition commit atomically and are idempotent by
  dialog action ID.

### 3. Interactive prop behaviors and room effects

Implement reusable built-in behavior services that scripts may compose:

- **Dispenser:** unlimited weighted choices, one shared persistent real-time
  cooldown per prop, default 10 minutes, direct-to-inventory grant, remaining
  time on rejection, newly placed ready.
- **Crafting station:** preview recipe, output, quantities, costs, and selected
  source stacks; revalidate and atomically consume/grant. Equipped stacks are
  used only when selected; slotted skills are ineligible.
- **Room aura:** idempotently active only while present and removed immediately
  on departure. Timed buffs/counter changes remain independent.
- **Environment state:** persistent prop/room state can enable visibility,
  lighting, exits, and actions; broadcast one revisioned update.
- **Room ownership:** grant/remove/modify through realtor services and tasks,
  with owner/editor authorization centralized.

### 4. Journal persistence and UI activation

Implement the Milestone 2 Journal UI against real data:

- `TaskDefinition`: ID, scope, title, description, ordered steps, progress
  triggers, sharing policy, reward, repeat/reset policy, and memory tags.
- `TaskProgress`: user/shared owner, status, per-step counters, started/
  completed timestamps, definition revision, and reward operation ID.
- Personal is default. Shared tasks explicitly define participants, credit, and
  reward recipients; room presence alone never grants credit.
- One-time completion and rewards are idempotent across duplicate events,
  reconnect, and restart. Repeatable tasks require explicit reset rules.
- Task view supports active/completed lists, step progress, selection, and
  Memories filtering by task tag.
- `Memory`: author, world, date/time, text, tags, source type, and optional task.
  Game-generated memories are immutable.
- Monthly Memories view uses configured game timezone, calendar day markers,
  list, tasks completed, Kudos earned, and new friends.
- New Memory saves current Chat Bar text. Users can edit/delete only their own
  manual memories; these operations never change task/reward history.

### 5. Room-owner editing

Activate the Edit Room core card only for the owner or an authorized editor:

- Show approved decorative prop library only.
- Select, add, delete, move, rotate, and scale instances using ray-cast
  selection and visible gizmos. Support mouse, touch, keyboard arrows, snap,
  Undo, and Escape cancel.
- Allow approved visual environment choices only; never expose gameplay auras.
- Room cards continue through normal drop/pickup/pin commands, not editor-only
  duplication.
- Maintain a local draft with base room revision. `Save layout` submits one
  validated patch. Reject stale revisions with an explicit reload/reapply path.
- Server verifies prop approval, transform bounds, instance IDs, ownership, and
  environment whitelist, then commits and broadcasts atomically.
- Unsaved close/navigation requires confirmation. A failed save preserves the
  local draft and shows the error.

### 6. World Editor and Card Database

Provide separate `/world-editor` and `/card-database` applications:

- Require the `world-editor` feature plus builder/game-master power for editing.
  Card Database is read-only to its configured authorized audience.
- World Editor edits a server-side draft copied from the published definition
  revision. Support rooms, board art/settings, props, initial room cards, exits,
  NPC placement, dialogs, activities, environment/gameplay settings, and
  ownership defaults.
- Include room list/search, room canvas, world-map graph, properties panel,
  prop library, validation panel, undo/redo, dirty markers, Save Draft, Discard,
  preview, and Publish.
- Save Draft never mutates the running world. Publish validates the entire
  content graph, writes files atomically, records a revision/backup, then
  reconciles live state.
- Reconciliation preserves user inventories, progress, ownership, and unrelated
  live room cards. Deleted rooms require an explicit confirmation; their orphaned
  room card stacks are then removed. Occupants and other live state are repaired
  lazily rather than eagerly rewritten.
- Card Database lists shared/world definitions, artwork, source scope, type,
  rarity, generated details, packs, recipes, and reference/validation errors.
  It never edits inventory or grants cards.
- Use the live Three.js room component in both editing surfaces rather than
  maintaining a second renderer.

### 7. Commands and powers

- Complete searchable command metadata and help UI.
- Powers are world-local: admin, realtor, builder, moderator, game-master.
- Implement realtor ownership commands; builder room/editor commands;
  moderator mute/kick/control commands; game-master gameplay/state commands.
- Forward `\` commands only for admin power and block `\r` and `\k`.
- Command and UI paths call the same service methods and permission checks.
- Audit privileged actions with actor, world, action, target, and result.
- Never infer an admin from account creation order; use explicit startup/profile
  configuration.

### 8. Trusted cross-world travel

- Add explicit `TRSERVER_TRUSTED_WORLDS` and optional
  `TRSERVER_TRUSTED_CA_FILE` validation. TLS verification remains enabled.
- Implement short-lived, signed, single-use transfer tickets bound to account,
  source/destination world, optional room, profile revision, and expiry.
- Source validates exit/access/Energy but does not charge or alter loadout until
  destination acceptance succeeds. Failure leaves the user unchanged.
- Destination validates trust, ticket, shared active-session generation, and
  entry access, then establishes the session and acknowledges transfer.
- On success charge normal room-change Energy, revoke the old session, close
  activities/dialogs, preserve shared state, remove source-native cards from
  equipment/skills, and load destination world state.
- Preserve the exact shared/world-scoped boundaries in the design, including
  shared Tired/Energy and world-scoped Sick, Stinky, Health, Cleanliness,
  custom counters, buffs, ownership, memories, tasks, and native cards.
- There is no general world chooser.

### 9. Activity completion hooks and Lazor Rush engine

- Extend the iframe bridge with signed activity events and operation IDs.
- Implement generic start-cost, result-validation, record, reward, abandon, and
  close hooks on the server.
- Implement Lazor Rush mechanics now: explicit Start/Play Again, 1 Energy start
  cost, continuous acceleration, pointer/touch laser behavior, fair visible-body
  collision, no pause on minimize/cover, and separate personal/world records.
- Only captured completed rounds count. Disconnect/close abandons without
  refund. The exact tutorial task/reward wiring is Milestone 4.

## Data and publishing rules

- Definition files describe initial content; SQLite stores dynamic live state.
- Every definition has a schema version and every publish has a revision.
- Store task/reward/purchase/craft/activity operation IDs in uniqueness-
  constrained ledgers.
- Use UTC instants for persistence and configured timezone only for game-day/
  month boundaries.
- Use transactional outbox/event records when a database mutation must be
  broadcast after commit; reconnect snapshots remain the recovery mechanism.
- World publish and live commands serialize through a world-level mutation lock
  or equivalent revision check.

## Required tests

### Behavior/dialog/task rules

- Handler dispatch for every event, tick non-overlap, per-instance state, script
  error containment, and transaction rollback.
- Dialog branching, hidden choices, side effects, invalid/stale choice,
  departure cancellation, and duplicate action ID.
- Personal/shared task credit, ordered multi-step progress, one-time reward,
  reconnect replay, repeat reset, and participant policy.
- Manual/game memory permissions and timezone month aggregation.

### Props, crafting, and editing

- Shared dispenser cooldown across users (in-memory, reset on restart) and weighted deterministic draw.
- Craft source-stack selection, equipped count/bonus update, invalid recipe
  rollback, and concurrent craft protection.
- Room aura enter/leave idempotency and independent timed consequences.
- Room-owner transform validation, stale revision conflict, unauthorized
  gameplay edit, undo/cancel, and atomic save.
- World draft isolation, invalid publish, destructive confirmation, backup, and
  live-state reconciliation.

### Security and administration

- Every power boundary through both command and HTTP/WebSocket UI paths.
- Admin command filtering and audit entries.
- Cross-world untrusted destination, bad/expired/replayed ticket, unavailable
  destination, successful handoff, session replacement, Energy charge, and
  native-card loadout removal/recovery.

### Browser

- Full dialogs in Look/Quick Actions bars.
- Journal task and monthly memory flows.
- Room editing with mouse, touch, keyboard, snap, undo, conflict, and save.
- World Editor draft/preview/publish and Card Database responsive views.
- Lazor Rush on mouse/touch, minimized and covered states.

## Definition of done

- A world author can add a scripted peep, dialog, task, interactive prop, recipe,
  and room aura using definitions plus a trusted script without changing core
  engine code.
- A room owner can safely personalize approved visuals but cannot create value
  or alter gameplay.
- A builder can draft, validate, preview, and publish a world without resetting
  unrelated live progress.
- Journal rewards, crafting, dispensers, and activity results are idempotent.
- Privileged UI and command paths share authorization and are audited.
- Two explicitly trusted local HTTPS servers pass a real cross-world handoff.
- All targeted tests pass.

## Manual review gate

Seed a small authoring world and ask the user to review:

1. Dialog pacing and action placement.
2. Journal readability and memory calendar behavior.
3. Room-owner editing precision on mouse and touch.
4. World Editor terminology, validation, preview, and publish confidence.
5. Behavior authoring clarity and error diagnostics.
6. Lazor Rush feel before tutorial reward tuning.

Resolve review feedback before building final tutorial content.
