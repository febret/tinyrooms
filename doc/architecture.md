# Tinyrooms — Technical Architecture (Milestone 1)

This document describes the technical architecture of Tinyrooms **as currently
implemented** (Milestone 1 vertical slice). It is a general guide to the
project components, a per-file inventory grouped by component, the
client/server protocol, and the main game flows.

Related docs: `doc/design.md` (product/design intent), `doc/milestone-1.md`
(Milestone 1 scope), `doc/milestone-2.md` / `milestone-3.md` / `milestone-4.md`
(future work), `doc/planning-hints.md`.

## 1. Overview

Tinyrooms is a multiplayer miniature-world game:

- **Authoritative server**: all world state lives in SQLite on the server.
  The browser client is a pure renderer + input dispatcher; it never invents
  game state.
- **Backend**: Python 3.11+, FastAPI + Uvicorn, `websockets`, PyYAML, SQLite
  (live world state), `cryptography` (self-signed TLS for local dev).
- **Frontend**: vanilla JavaScript ES modules (no app build step), Three.js
  for the 3D board renderer, same-origin iframe activities.
- **Content**: human-readable YAML under `worlds/` and `data/`, validated by
  loaders in `server/content/`.
- **Transport**: HTTPS JSON API for accounts/session/bootstrap/stickers/
  activities plus one sequenced JSON WebSocket (`/ws`) per logged-in client
  for commands, snapshots, and room events.
- **Runtime topology** (single process):

```
browser (app/js + Three.js + activity iframes)
  |  HTTPS: /api/*, /app/*, /activities/*, /assets/*
  |  WSS: /ws (cookie session + Origin check)
  v
run.py (TLS cert + Uvicorn) -> server/app.py (FastAPI assembly)
  -> server/commands (parse + dispatch)
  -> server/services (rooms / cards / activities)
  -> server/state (SQLite via DatabaseHub) + server/profiles.py (accounts)
  -> server/content (YAML world + card catalogs)
```

Key design decisions:

- Invitation-gated accounts (`TRSERVER_NEW_ACCOUNT_PASSPHRASE`); changing it
  later does not affect existing users.
- Rotating opaque sessions (HttpOnly `tr_session` + `tr_csrf` cookies, CSRF
  header on POSTs); one live gameplay session per account (generation
  counter; old socket gets `session.replaced`).
- Mandatory initial Sticker Designer activity gates world entry
  (`initial_sticker_complete`, WS close `4403` until confirmed).
- Sequenced room broadcasts: per-room monotonic `seq` in SQLite; clients
  track `currentRoomSeq` and re-request a snapshot on gap.
- Feature flags via `TRSERVER_FEATURES` (currently `dev_sample_activity`).
- Milestone 1 playable rooms are `hub` + `playroom`; other tutorial rooms
  load/validate as content but `.go` there is rejected.

Configuration (`server/config.py`, env `TRSERVER_*`): `NEW_ACCOUNT_PASSPHRASE`
(required), `HOST` (`127.0.0.1`), `PORT` (`5000`), `USERS_PATH` (`users`),
`WORLD_PATH` (`worlds/tutorial`), `WORLDSTATE_PATH`
(`.local/worldstate.sqlite3`), `FEATURES`, `TIMEZONE` (`UTC`).

## 2. Component guide

| Component | Path(s) | Responsibility |
| --- | --- | --- |
| Launcher | `run.py` | Dev HTTPS entrypoint: cert reuse/generation, Uvicorn bootstrap, bounded shutdown. |
| HTTP + WS assembly | `server/app.py` | FastAPI routes, auth enforcement, static/activity/asset serving, WS command loop. |
| Config | `server/config.py` | Env parsing/validation, path containment, feature flags. |
| Security | `server/security.py` | Password hashing, session/CSRF tokens, origin checks, rate limiting. |
| Accounts | `server/accounts.py`, `server/profiles.py` | Auth service + SQLite account/session/inventory/world-profile repository. |
| Protocol | `server/protocol.py` | WS envelope constants, validation, and serializer helpers. |
| Live connections | `server/connections.py` | In-memory WS registry, per-account queue, room membership, session replacement. |
| Commands | `server/commands/` | `.`-command/chat/`\admin` parser, name→handler registry, 11 core handlers + dispatcher. |
| Content loaders | `server/content/` | Strict YAML loading for cards/packs and world/rooms/props/peeps. |
| Room service | `server/services/rooms.py` | Snapshots, presence, chat, navigation. |
| Card service | `server/services/cards.py` | Card serialization, atomic pickup/drop, core favorites. |
| Activity service | `server/services/activities.py` | One-live-activity-per-account lifecycle (in-memory). |
| Persistence | `server/state/` | Dual-DB schema (`DatabaseHub`) + room state (seq, chat, room cards). |
| Browser UI | `app/` | Shell (`index.html`), styles, 14 JS modules, vendored Three.js. |
| Activities | `activities/` | Same-origin iframe games + shared `TinyActivity` bridge. |
| Shared data | `data/` | Core tuning YAML, base card set + art, sticker choices. |
| Tutorial world | `worlds/tutorial/` | `The Little House` rooms/props/peeps/cards/recipes + art/models. |
| Tests | `tests/` | Python `unittest` (server/integration/static) + Playwright browser specs. |
| Tooling | `tools/`, root configs | Browser-test server, dep vendoring, Playwright/npm config. |

`server/client/` and `tests/client/` are referenced in `AGENTS.md` as the
future home of browser-free ports of `app/js/` logic, but do not exist yet in
this checkout.

## 3. HTTP API (`server/app.py`, `app/js/api.js:PATHS`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | `{ok, protocol_version: 1}`. No auth. |
| `GET` | `/api/stickers` | `{ok, stickers: [{name, image_url}]}` from `data/stickers`. No auth. |
| `GET` | `/api/session` | `{ok, logged_in, csrf_token?, user?}` from `tr_session` cookie. |
| `POST` | `/api/auth/create` | `{username, password, passphrase?}`; passphrase-gated, `Origin`-checked; sets `tr_session` + `tr_csrf`; returns `{ok, csrf_token, user}`. |
| `POST` | `/api/auth/login` | Same minus passphrase; evicts old WS with `session.replaced`. |
| `POST` | `/api/auth/logout` | Cookie + `Origin` + `X-CSRF-Token`; closes activity, revokes session, pushes `session.replaced`, clears cookies. |
| `POST` | `/api/stickers/confirm` | `{sticker}`; idempotent first-free confirm; closes sticker activity; returns `{ok, user}`. |
| `GET` | `/api/bootstrap` | Cookie auth (no CSRF); `{ok, user: {…, can_enter_world}}`. |
| `GET` | `/api/activities/current` | `{ok, activity\|null}`; forces sticker activity when incomplete. |
| `GET` | `/api/activities/{activity_id}` | Serialized activity or 404 on id mismatch. |
| `POST` | `/api/activities/{activity_id}/bridge` | `{type, payload}`; `type ∈ {activity.ready, activity.attention, activity.cancel, activity.complete}`. |
| `GET` | `/` | `app/index.html` or fallback text. |
| `GET` | `/app/{path}` | Static app files (path-contained). |
| `GET` | `/activities/{name}/`, `/activities/{name}/{path}`, `/activities/shared.js\|shared.css` | Activity hosting (fallback page outside Milestone 1). |
| `GET` | `/assets/stickers/{file}`, `/assets/base/{file}`, `/assets/world/{world}/{cards\|rooms\|props\|peeps}/{file}` | Art serving; traversal → 404. |

Serialized `user`: `{id, username, sticker, initial_sticker_complete,
favorites[], level, kudos, bops, shared_energy, show_activity_log, world_id,
remembered_room, inventory[], core_cards[], activity}` (favorites/
show_activity_log sourced from `user_profiles.profile_json`; `core_cards` are
the core card definitions (hand cards first in their cards.yaml `order`,
followed by unordered core UI chrome such as the expand/collapse arrows).
New users: level 0 “Guest”, 10 Bops, Smile/Sigh/Growl/Goof, favorites `[Room,
Emotes, Inventory]`.
Authenticated POSTs require `Origin` + `X-CSRF-Token == tr_csrf ==
session.csrf_token`.

## 4. WebSocket protocol (`/ws`)

Limits: `PROTOCOL_VERSION=1`, `MAX_COMMAND_SIZE=1024`,
`MAX_CHAT_SIZE=280`, `MAX_HISTORY_MESSAGES=50`, `MAX_SEND_QUEUE=128`.
Auth: `tr_session` cookie + `Origin` header. Close codes: `4401`
(no/invalid session), `4403` (origin fail or sticker-incomplete). Per-message
re-auth on generation mismatch (one gameplay session per account).

### 4.1 Client → server (`parse_client_message`)

| `type` | Fields |
| --- | --- |
| `command` | `{v:1, type:"command", request_id: str (non-empty, ≤80), command: str (non-empty, ≤1024)}` — raw command string, e.g. `.go @way:exit0`. One private `result` per `request_id` (`Date.now()-rand` on the client). |
| `snapshot.request` | `{v:1, type:"snapshot.request"}` — sent by client on seq gap. |

### 4.2 Server → client

| `type` | Fields |
| --- | --- |
| `room.snapshot` | `{v:1, type:"room.snapshot", seq: int, room: {...}}` — full state, replaces render. |
| `room.event` | `{v:1, type:"room.event", seq: int, event: {...}}` — incremental broadcast. |
| `result` | `{v:1, type:"result", request_id, ok: bool, events: [...private], code?, message?, payload?}` — per-command ack. |
| `session.replaced` | `{v:1, type:"session.replaced", message}` — forced sign-out. |
| `error` | `{v:1, type:"error", code, message}` — protocol-level, no disconnect. |

### 4.3 Sequencing / ack

- Strict envelope `v==1`, else `protocol_error`.
- Room-scoped monotonic `seq` (`advance_room_seq` per room, SQLite txn).
  Join: advance → private snapshot → broadcast `presence.enter` to others.
  `.go`: two seqs (source + dest), private dest snapshot + `presence.leave`
  (old) + `presence.enter` (new). Chat/pickup/drop: one seq + broadcast.
- Client tracks `currentRoomSeq`; on `room.event` with
  `seq != current+1` it adopts the incoming seq, sends
  `snapshot.request`, and drops the event; server replies with a fresh
  snapshot.
- Ack: `pending: Map<request_id → {resolve, reject}>`; `result.ok`
  resolves, else rejects. Malformed JSON/version/type → `error` envelope,
  connection stays open. Send path: `asyncio.Queue(128)`; full raises.

### 4.4 Activity host↔guest bridge (same-origin `postMessage`)

Host→guest: `tinyrooms.host.state {activityId, state:{user, room, stickers,
activity, config}}`, `tinyrooms.host.result {activityId, requestId, ok,
message, payload, state}`. Guest→host: `tinyrooms.activity.{ready, command,
sticker.confirm, attention, close}` (strict origin + activityId +
source-window match). `command` runs through the WS pipeline; `attention`
→ `POST bridge activity.attention` → titlebar flash.

## 5. Command reference

Grammar (`parser.py`, `app/js/commands.js`): bare text → `say` (client
pre-wraps to `.say "<quoted>"` unless already `.`/`\`); `.name args…` via
shlex (name lowercased); `\…` → `admin` → always rejected. Targets:
`@card:<stack>`, `@prop:<instance>`, `@peep:<id>`, `@way:<exit>`,
`@<username>`. Unknown `.name` → rejection.

| Command | Example | Effect |
| --- | --- | --- |
| `.help` | `.help` | Private `payload.commands:[{name, summary}]` (12 commands). |
| `.look` / `.inspect` | `.look @card:<stack>` | Private `payload.entity`. No state change. |
| `.go` | `.go @way:exit0` | Exit/lock/card + Milestone-1 room checks; updates `remembered_room`, moves WS room, closes room-bound activity; private dest snapshot + 2 broadcasts. |
| `.say` | `.say "hi"`, `(!) hi` | `(.)`→`thinking`, `(!)`→`spiky`, else `normal`; persists to bounded history; broadcasts `chat.message`. Empty / >280 chars rejected. |
| `.pickup` | `.pickup @card:<stack> 2` | Atomic room→inventory txn; private `payload.inventory`; broadcasts `room.card.updated/removed`. Pinned rejected; concurrent same-stack is single-winner. |
| `.drop` | `.drop @card:<stack> 1 62 71 0` | Atomic inventory→room txn; optional trailing `x y z` floor coordinates (percent x/y, elevation z; clamped, defaults `50 50 0`); broadcasts `room.card.added`. |
| `.favorite` | `.favorite @card:journal` | Core-card-only toggle; `payload.favorites`. |
| `.play` | `.play sample`, `.play molly replace` | Starts activity (`molly`→`lazor-rush` playroom-only; `sample`→`dev-sample` flag-gated; also `shop`/`crafting`); occupied without `replace` → reject; private `activity.started` (+`closed reason:replaced`). |
| `.cancel` | `.cancel` | Closes current activity (`reason:cancelled`); none-open → reject. |
| `.settings` | `.settings action-log off` | Persists `show_activity_log`; `payload.{show_activity_log}`. |
| `.reset_room` | `.reset_room` | Deletes all live cards in the current room and re-inserts the YAML seeds in one txn; private fresh snapshot + `room.cards.reset` broadcast. Open to anyone for now (TODO: admin-only once Milestone 2 roles exist). |

Quick actions are server-provided (`Look`, `Pick up 1`, `Drop 1`, exit
labels, `Look around`); the client never invents them.

## 6. Main game flows

### 6.1 Account creation / login + session

1. `GET /api/session` → `{logged_in:false}` → login screen.
2. Create `POST /api/auth/create {username, password, passphrase}` +
   `Origin`. Wrong passphrase → 401, duplicate (casefold) → 409, missing
   origin → 403. Success persists the account, sets cookies, returns
   `user{initial_sticker_complete:false}`.
3. Login `POST /api/auth/login`; a live old WS gets `session.replaced` and
   loses command authority (generation check per message).
4. Logout `POST /api/auth/logout` → closes activity, revokes session,
   pushes `session.replaced "You signed out."`, clears cookies. Later WS
   messages → `session_missing` + close.
5. Plain disconnect: `presence.leave` broadcast, activity closed,
   `remembered_room` retained. Creation/login are source/username
   rate-limited.

### 6.2 Onboarding / Sticker Designer (mandatory)

1. After create, `GET /api/activities/current` / `user.activity` =
   `{kind:"sticker-designer", iframe_url:"/activities/sticker-designer/?session_id=<uuid>",
   room_bound:false}`. Client opens a required modal iframe; chat is inert,
   `Escape` cannot dismiss, no WS is opened yet.
2. Choices come from `GET /api/stickers`, never hardcoded.
3. Interruption: every login re-ensures the designer; `/ws` closes `4403`
   until confirmed.
4. Confirm: guest `postMessage sticker.confirm` → host
   `POST /api/stickers/confirm {sticker}` (idempotent) → activity closed,
   `user{sticker, initial_sticker_complete:true}` → modal removed, chat
   enabled. Later “Swap Sticker” reopens the same kind as a cancellable
   non-modal.

### 6.3 Room enter / travel / presence

1. WS connect → `current_room_for_account` (`remembered_room` if still in
   world, else `hub`) → `set_room` → private `room.snapshot(seq)` →
   broadcast `presence.enter` to others.
2. Tutorial edges: `hub --exit0--> playroom`,
   `playroom --hub--> hub` (plus non-Milestone `playroom→foyer`, filtered).
3. `.go @way:exit0`: mover gets the dest snapshot; old room sees
   `presence.leave{…, destination_room_id}`; new room sees
   `presence.enter{…, source_room_id}`; room-bound activities auto-close
   (`reason:room_changed`). Two clients observe join/leave/chat in seq
   order.
4. Restart/resume: `remembered_room` + inventory persist (e.g. picking up
   `fancy-wallet` in playroom survives a server restart).

### 6.4 Chat

Chat bar → `chatToCommand` → `command` envelope → `.say` →
`result{ok, message:"Message sent."}` + `room.event chat.message`. Bubbles
beside peeps (styles normal/thinking/spiky; click dismisses; capped list);
`chat_history` capped at 50 server- and client-side. The command menu
inserts verbs verbatim (not wrapped in `.say`); rejections surface as an
error toast.

### 6.5 Card inspect / pickup / drop / favorites

- Snapshot `room_cards[]` (`{stack_id, quantity, pinned, definition,
  quick_actions:[Pick up 1], position}`) and `inventory[]`
  (`{…, scope, world_id, equipped}` + `Drop 1`).
- Inspect (`Inspect` / `.look @card:<stack>`) is a pure read (front/back,
  rarity, descriptions).
- Pickup (Room view → `Pick up` → qty dialog → `.pickup @card:<stack> n`)
  → private `payload.inventory` + broadcast updated/removed. Pinned stacks
  reject.
- Drop (Inventory view → `Drop` → `.drop @card:<stack> n`, or dragging an
  equipped hand tile onto the board) → broadcast `room.card.added` with the
  persisted `position`. `app/js/drag.js` raycasts the pointer onto the floor
  plane (`board.screenToBoardPosition`), shows a drop marker, sends the
  trailing `x y z`, and plays a DOM card-flight animation; pick-up from the
  board/Room view plays the reverse flight. Starter Smile/Sigh/Growl/Goof +
  10 Bops only; core cards are non-transferable.
- Favorites (expand core `>` → select → `Favorite` /
  `.favorite @card:journal`) → `payload.favorites`, visible via
  `/api/bootstrap`. Escape priority: targeting → popup → main view.

### 6.6 Activity window lifecycle

Server: one session/account
`{id, kind, title, iframe_url, bridge_url, room_bound, room_id, attention}`.
`.play` kinds: `molly→lazor-rush` (playroom-only), `lazor-rush|shop|
crafting`, `sample→dev-sample` (flag-gated). `start` rejects when occupied
unless `replace`; `close`, `close_if_room_bound` (on `.go`/logout/
disconnect), `mark_attention`. Host iframe
`/activities/<kind>/?session_id=…` with the §5.4 bridge; window chrome
(drag/arrow-keys, minimize/maximize/close, z-order); mandatory sticker
variant hides controls + traps focus/inert. `closed` is also appended to
private result events for `.play replace`/`.cancel`/nav so the store clears
`activities[]`.

## 7. Testing architecture

- Python `unittest`: `test_milestone1.py` (config/security/parser,
  content/persistence, accounts/sessions, multiplayer gameplay via
  TestClient + temp dirs), `test_launcher.py` (cert/shutdown),
  `test_ui_presentation.py` (HTML landmarks, live-server contract,
  stylesheet wiring, <1200-line rule).
- Playwright (`tests/browser/`): per-test HTTPS subprocess fixture with
  isolated `.browser-runtime/run-*` users/SQLite/certs; `flows.spec.js`
  (functional), `screenshots.spec.js` (20 captures × desktop/portrait).
  Baselines under `tests/browser/baselines/` require manual design review;
  update only with `TR_UPDATE_SCREENSHOTS=1`.
