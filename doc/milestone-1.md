# Milestone 1 - Multiplayer Foundation

## Outcome

Deliver a secure, persistent, playable vertical slice in which a new user can
create an account, choose a sticker, enter the tutorial Hub, chat with another
user, move between the Hub and Playroom, select and inspect cards, transfer room
cards, and open/close a sample activity. The server is authoritative and all
user interactions travel through the same command-string pipeline.

This milestone establishes contracts that later milestones extend. Do not defer
protocol, persistence, authentication, or concurrency correctness.

## Source of truth and reuse policy

Read these before implementation:

1. [design.md](./design.md), especially Users, UI, Cards, Room Design,
   Activities, Commands and Administration.
2. [planning-hints.md](./planning-hints.md), especially Accounts, Client and
   Presentation, Content Definitions, World State, Activities, and Commands.
3. The prototype references called out below.

When sources differ, implement the current design and planning hints. The
prototype is structural reference only.

Useful prototype patterns:

- Reuse the idea of separate immutable definitions and mutable state from
  [world.py](../attic/tinyrooms-prototype/tinyrooms/world.py) and
  [db.py](../attic/tinyrooms-prototype/tinyrooms/db.py).
- Reuse the command registry's small `CommandSpec` concept from
  [registry.py](../attic/tinyrooms-prototype/tinyrooms/commands/registry.py), but
  support the current `.` normal-command and `\` admin-command syntax.
- Reuse the ordered full-sync plus entity-delta idea from
  [room.py](../attic/tinyrooms-prototype/tinyrooms/room.py).
- Reuse the prototype integration-test isolation approach documented in
  [testing.md](../attic/tinyrooms-prototype/doc/testing.md).

Do **not** copy the prototype's Flask/Socket.IO server, PixiJS room renderer,
plaintext credential cookie handling, room-coordinate peeps, or `:` command
syntax. This release requires FastAPI/uvicorn, native WebSockets, Three.js,
secure server-side authentication, room-granularity peep locations, and the
current command grammar.

## Prerequisites and milestone boundary

- The repository already contains design references, core data, tutorial data,
  activities folders, and assets. Treat those as input content, not proof that
  runtime behavior exists.
- Milestone 1 owns foundational schemas and APIs. Future migrations must remain
  backward compatible with accounts and live state created here.
- Rich props, NPCs, stats, progression, and complete overlays are Milestone 2.
- Behavior scripts, dialogs, editors, Journal logic, and task automation are
  Milestone 3.
- Full tutorial content and production polish are Milestone 4.

## Target structure

Keep every source file below 1,200 lines and document public cross-module
functions.

```text
run.py
server/
  app.py                 # FastAPI assembly and lifespan
  config.py              # validated environment/CLI configuration
  security.py            # password hashing, sessions, CSRF/origin checks
  accounts.py            # account creation/login/sticker completion
  profiles.py            # shared profile repository
  protocol.py            # typed WebSocket envelopes and serializers
  connections.py         # active-session and room connection registry
  commands/
    registry.py
    parser.py
    core.py
  content/
    cards.py
    worlds.py
  state/
    world_state.py
    migrations.py
  services/
    rooms.py
    cards.py
    activities.py
app/
  index.html
  css/
  js/
    api.js
    socket.js
    state.js
    commands.js
    board.js
    cards.js
    activities.js
    ui.js
  vendor/three/
activities/
  sticker-designer/
tests/
  unit/
  integration/
  browser/
tools/
  vendor_browser_deps.py
```

Use this structure and preserve these responsibility boundaries. Do not create
a single server or client file that owns unrelated systems.

## Architecture contract

### Process and configuration

- `run.py` launches uvicorn over HTTPS and defaults to `127.0.0.1:5000`.
- Generate a temporary self-signed certificate under `.local/` when no
  certificate is supplied. Reuse it until expiry; never commit keys.
- Validate these settings at startup:
  `TRSERVER_NEW_ACCOUNT_PASSPHRASE`, `TRSERVER_USERS_PATH`,
  `TRSERVER_WORLD_PATH`, `TRSERVER_WORLDSTATE_PATH`, `TRSERVER_FEATURES`,
  `TRSERVER_TIMEZONE`, `TRSERVER_HOST`, and `TRSERVER_PORT`.
- Fail startup with a clear message for invalid paths, malformed content,
  conflicting IDs, or an invalid timezone. Never silently substitute broken
  gameplay definitions.
- Serve only explicit static roots. Profile and SQLite paths must never be
  reachable as static content.

### Authoritative server and command path

All UI actions become command strings before reaching gameplay code:

```text
UI gesture -> command string -> WebSocket command envelope
-> parser -> permission/target validation -> transaction
-> private result + room events -> client state/render
```

- Chat text without a leading `.` is dispatched as the chat command.
- Normal commands begin with `.`. Implement at least `.help`, `.look`, `.go`,
  `.say`, `.inspect`, `.pickup`, `.drop`, `.favorite`, `.play`, and `.cancel`.
- Reserve `\` for admin console commands, but do not expose admin execution yet.
- Parse typed target tokens exactly as designed:
  `@card:<id>`, `@prop:<instance_id>`, `@peep:<id>`, `@<username>`, and
  `@way:<id>`.
- Quick actions are server-provided command templates. The client must not
  invent permissions or action availability.
- One command handler performs validation and mutation atomically. A rejected
  command emits a visible error and changes no energy, cards, location, or
  activity state.

### WebSocket protocol

Use versioned JSON envelopes:

```json
{"v":1,"type":"command","request_id":"uuid","command":".go @way:portal"}
{"v":1,"type":"result","request_id":"uuid","ok":true,"events":[...]}
{"v":1,"type":"room.snapshot","seq":42,"room":{...}}
{"v":1,"type":"room.event","seq":43,"event":{...}}
```

- Every client command has a unique request ID and exactly one private result.
- Room events have a monotonically increasing room sequence. On a gap, the
  client requests a fresh snapshot rather than guessing.
- Define events for room presence, chat, room navigation, room-card changes,
  selection invalidation, forced sign-out, activity lifecycle, and visible
  rejection.
- A room join sends one coherent snapshot before subsequent deltas. Serialize
  outbound DTOs; never expose persistence objects.
- Bound chat history, message size, command size, and send queues. Reject
  malformed envelopes without disconnecting a well-behaved client.

## Work packages

### 1. Project bootstrap and quality gates

- Create FastAPI application/lifespan setup, HTTPS launcher, static serving,
  local Three.js vendoring, and development requirements.
- Add unit, integration, and browser-test commands without introducing a
  framework beyond the repository's declared dependencies.
- Add a disposable test runtime that uses temporary profile/world-state paths
  and an ephemeral port.
- Add structured server logs with request/session IDs but never passwords,
  passphrases, session tokens, or full chat payloads.

### 2. Account and profile lifecycle

Implement:

- Unique usernames compared case-insensitively and stored in their original
  user-entered casing for display.
- Password hashing using a modern salted KDF available to the implementation;
  compare hashes in constant time.
- Account creation gated by `TRSERVER_NEW_ACCOUNT_PASSPHRASE`.
- Rate limits for create/login attempts per source and username.
- Opaque, rotating server-side session tokens in secure, HTTP-only,
  same-site cookies. WebSockets authenticate from the established session.
- One active gameplay session per account. A newer login or world entry sends
  `session.replaced` to the old connection and immediately revokes its command
  authority.
- Shared profile fields required by later milestones: account ID, username,
  password hash, sticker, initial-sticker-complete flag, favorites, level,
  Kudos, Bops, global cards, friends, pending friend requests, shared Energy,
  last Energy timestamp, last daily claim, and active session generation.
  Fields not used yet receive design-defined defaults.
- World profile fields: remembered room, native cards, local counters/buffs,
  tasks, memories, ownership, and last visit.

Do not put account data in the world-state database. This separation is required
for cooperating worlds later.

### 3. Account creation and Sticker Designer activity

- The login screen has Login and Create New Account flows with inline,
  accessible validation.
- Creating valid credentials persists the account immediately, then opens
  Sticker Designer as the one fully modal activity.
- Load choices from `data/stickers`; do not hard-code sticker filenames.
- The first confirmed sticker is free. Until confirmation, every login resumes
  Sticker Designer and world entry is denied.
- Confirmation is idempotent. A retried request cannot charge or grant twice.
- Implement the reusable activity host now: iframe at a separate URL,
  postMessage bridge with strict origin/type validation, title bar, drag,
  minimize, maximize, close, attention flash, and a server-owned activity
  session ID.
- Enforce one activity per user. Replacing an activity requires explicit
  confirmation. Logout/disconnect closes it.
- Add a small developer-only/sample activity fixture for lifecycle tests; do
  not expose it in production navigation.

### 4. World definitions and live state

- Load `world.yaml`, `rooms/*.yaml`, `cards/*.yaml`, and core card sets into
  validated immutable registries.
- Use stable world, room, exit, card-definition, card-stack, and card-instance
  IDs. Reject duplicate or dangling references at startup.
- Keep definition YAML read-only during ordinary play.
- Store dynamic room cards, prop state placeholders, room ownership,
  per-world user location, and monotonic room revision/sequence in SQLite.
- Use migrations and foreign keys. Wrap multi-table mutations in transactions.
- Overlay live state onto definitions at load without erasing newly added
  definition content or duplicating initial room cards.
- Returning users resume in their remembered accessible room; otherwise move
  them to the entry room and visibly explain the fallback.
- Disconnected peeps leave active room presence immediately.

### 5. Basic room navigation and chat

- Implement Hub and Playroom definitions sufficient for this milestone, using
  the supplied [rooms.yaml](../worlds/tutorial/rooms/rooms.yaml) entries and
  assets. Other rooms may load but need not be playable yet.
- The room snapshot contains metadata, exits, occupants, room cards, environment
  placeholder, and available quick actions.
- `.go` validates the source room, exit, lock/access state, destination, and
  current session before changing location.
- Broadcast leave and enter events in order. Never show a peep in two rooms.
- Normal chat is room-scoped and stored in a bounded recent history.
- Parse `(.)` and `(!)` prefixes into thinking and spiky bubble styles.
- The UI shows speech bubbles beside peeps; repeated text fills to a defined
  character limit and replaces oldest text. Click/tap dismisses with a
  zoom/fade animation.
- Implement a collapsible Action Log controlled by persisted
  `show_activity_log`, hidden by default. Rejections remain visible even when it
  is hidden.

### 6. Basic card interaction

Implement enough of the final model that Milestone 2 extends rather than
replaces it:

- Load core and collectible card definitions from `data/cardsets/*` and the
  world's `cards/` directory. Core cards are non-collectible.
- Represent owned and room cards as stacks with stable stack IDs, definition
  IDs, quantity, scope, equipped flag, pinned flag, and room position where
  applicable.
- Render physical-looking cards with front/back, hover/touch lift, selection,
  and card-hand sounds. Selecting a collectible never auto-plays it.
- Implement the Card View shell, favorite core cards, expand/collapse control,
  Look Bar, Quick Actions Bar, Room View, basic Inventory View, and Card Details
  popup. More complete filtering/equipment appears in Milestone 2.
- New users receive only Smile, Sigh, Growl, and Goof, plus 10 Bops; they start
  with empty equipment and Room/Emotes/Inventory favorites.
- Implement atomic room-card pickup/drop quantities and pin enforcement.
  Slotted-skill rules can be inactive until Milestone 2, but the data model must
  already distinguish card type.
- Close or retarget views according to the design when cards disappear.

### 7. Responsive main screen and Three.js board shell

- Build the single-page layout: Peeps List, Three.js Board, Card View, Look Bar,
  Quick Actions Bar, Chat Bar, optional Action Log, modal layer, and activity
  layer.
- Render the room floor as a rotatable/zoomable Three.js board with mouse,
  touch, pinch, and keyboard-safe controls. The board is not a 2D sprite stage.
- Render simple card markers and placeholder transform nodes for future props;
  use supplied final room art where available, not programmer-art rectangles.
- Implement the view stack contract: one main Board-modal view, optional nested
  Card Details, activities below Board-modal views, visible Close controls, and
  Escape priority of targeting then popup then main view.
- For portrait phones, preserve chat, current quick actions, own peep, and
  favorite cards; collapse secondary panels rather than shrinking tap targets
  below 44 CSS pixels.

## Required tests

### Unit

- Config validation and path containment.
- Password verification, session rotation, username normalization, and
  passphrase failure.
- Command tokenization, quoting, target parsing, permission metadata, and
  malformed command rejection.
- YAML validation, duplicate IDs, dangling exits/cards, and definition/live
  state overlay.
- Card stack quantity and pickup/drop/pin invariants.

### Integration

- Account creation fails with the wrong passphrase and succeeds once with the
  right passphrase.
- Interrupted sticker selection resumes and blocks world entry.
- A second login revokes the first session.
- Two clients see join/leave, chat, bubble style, and room transitions in order.
- Concurrent pickup of one room stack has one winner; the loser gets a visible
  rejection and no duplicated cards.
- Reconnect restores the remembered room and inventory.
- Activity replacement, disconnect, room-bound closure, and invalid iframe
  messages follow the lifecycle contract.

### Browser

- Desktop and phone-portrait account creation through sticker confirmation.
- Board rotate/zoom with mouse and touch.
- Chat bubbles, Action Log toggle, core-card favorites, Room/Inventory views,
  Card Details, quantity pickup/drop, modal layering, and Escape behavior.
- Capture deterministic screenshots corresponding to the applicable images in
  `doc/images`.

## Definition of done

- Two real browsers can create separate users, enter the Hub, chat, navigate to
  Playroom and back, and observe consistent presence.
- A newly created account survives a server restart without duplicate grants.
- Room cards survive restart and cannot be duplicated under concurrent pickup.
- All user actions use command strings and server validation; no client-only
  mutation determines gameplay state.
- The Sticker Designer is a separate iframe activity and is mandatory only for
  the initial choice.
- The main screen works at 1280x800 and 390x844 without inaccessible controls.
- Targeted automated tests pass from a clean disposable data directory.

## Manual review gate

Pause after automation and give the user one review build plus a short checklist:

1. Account/login wording and sticker-selection flow.
2. Board rotation/zoom feel on desktop and touch.
3. Card proportions, selection animation, and interaction sounds.
4. Chat readability, bubble dismissal, and action-bar clarity.
5. Hub/Playroom navigation and responsive layout.

Record requested visual/interaction tweaks and complete them before Milestone 2.
Do not use this review to add Milestone 2 gameplay.
