# Tinyrooms — Technical Architecture

This guide describes component boundaries and runtime contracts. Product
requirements belong in [design](design.md); setup and verification commands in
[README](../README.md). Source links below replace field, endpoint, and command
inventories so those details have one authority.

## 1. Overview

The server owns gameplay state and validates every action. The browser renders
snapshots/events and dispatches input; it does not invent authoritative state.
One process owns a world, with SQLite persistence and validated YAML content.
The frontend uses vanilla ES modules and Three.js, without an app build step.
`npm run vendor` copies Three.js and Drawflow (the World Editor's node graphs)
into the ignored `app/vendor/`.

```text
browser (app + Three.js + same-origin activity iframes)
  | HTTPS: account/bootstrap APIs, assets, activity bridge
  | WSS: commands, snapshots, room events
  v
run.py -> server/app.py
  -> commands -> services -> state / profiles
  -> content loaders + mods + authored behaviors
```

Mission Control is a separate optional process for player entry and fleet
operations. MC and participating worlds share a profile database; each world
has its own worldstate database. See the canonical
[entry/topology contract](mission-control.md#2-terminology-and-topology) and
[deployment/upgrade guidance](mission-control.md#83-deployment-and-upgrades).

## 2. Component guide

| Boundary | Source entry points |
| --- | --- |
| HTTPS launch and application assembly | [run.py](../run.py), [server/app.py](../server/app.py) |
| Environment parsing and security | [config](../server/config.py), [security](../server/security.py) |
| Accounts and profile persistence | [accounts](../server/accounts.py), [profiles](../server/profiles.py), [serialization](../server/serialization.py) |
| Protocol and live connections | [protocol](../server/protocol.py), [connections](../server/connections.py) |
| Command parsing/dispatch | [parser](../server/commands/parser.py), [registry](../server/commands/registry.py) |
| Gameplay services | [server/services/](../server/services/) |
| Persistence and migrations | [server/state/](../server/state/); [durability contracts](db.md) |
| Content and extensions | [server/content/](../server/content/), [mods](../server/mods.py), [behaviors](../server/behaviors/) |
| Browser rendering and state | [app/js/](../app/js/), [app/css/](../app/css/) |
| Embedded activities | [activities](../activities/), [client host](../app/js/activities.js), [server lifecycle](../server/services/activities.py) |
| MC and world management channel | [server/mission_control/](../server/mission_control/), [mission-control UI](../mission-control/), [mc_client](../server/mc_client.py), [mc_api](../server/mc_api.py) |

### 2.1 Content and mods

[Content loaders](../server/content/) define accepted YAML and validation.
[Shared data](../data/) supplies core tuning, cards, artwork, effects, and scenes;
[tutorial content](../worlds/tutorial/) supplies world-specific definitions.

[The mod loader](../server/mods.py) owns manifest discovery, enabled-mod selection,
content merging, command registration, and runtime factories. Worlds declare
`requires_mods`; startup rejects missing dependencies. The scammon-academia
world requires [classrooms](../mods/classrooms/). Mod `prepare()` runs before
world seeding so persisted dynamically materialized rooms can receive their
seeds.

Prop schema and file-wide scale settings are defined by
[worlds.py](../server/content/worlds.py). Effect definitions are loaded by
[fx.py](../server/content/fx.py) and rendered by
[prop-effects.js](../app/js/prop-effects.js); reduced motion suppresses effects.
Props may also declare named mesh `states` and an authored `active_state`.
[rooms.py](../server/services/rooms.py) can switch a room instance's state at
runtime and broadcasts `room.prop.updated`; clients reload the active model.

Rooms may set `sprites_enabled: true` to draw every present peep as a
camera-facing 2D sprite on the board. [sprite_rooms.py](../server/services/sprite_rooms.py)
owns the in-memory, server-authoritative floor positions, keeps them clear of
authored prop footprints, and re-randomizes on room entry. Behavior scripts can
read `context.sprites_enabled` and queue `move_sprite`, `move_sprite_random`, or
`move_peep`; the client projects sprite heads to anchor scaled speech and emote
bubbles over them.

### 2.2 World-resolved card effects

Generic stat/lighting effects belong to core services. Other prop-targeted card
plays are delegated through [gameplay commands](../server/commands/gameplay.py)
to authored behaviors. The core must not hardcode world-specific effect names.
An unrelated prop is a no-op: charge Energy and consume one-use cards only when
the behavior resolves. See the tutorial's
[litter tray](../worlds/tutorial/props/litter-tray.py) and
[centipedes](../worlds/tutorial/props/centipedes.py) for authored examples.

## 3. HTTP and session boundaries

[Application assembly](../server/app.py), [route modules](../server/routes/), and
[client API](../app/js/api.js) define endpoints and payloads; serializers live in
[serialization.py](../server/serialization.py). Do not maintain parallel tables.

- Account creation is invitation-gated; invitation changes do not affect existing
  accounts. Password/session handling and Origin/CSRF checks belong to
  [security](../server/security.py) and [accounts](../server/accounts.py).
- A new login replaces the old gameplay session. Old sockets lose authority,
  rather than merely showing a sign-out message.
- Initial Sticker Designer completion is mandatory before world entry. Closing
  or interrupting onboarding does not bypass the gate; subsequent login resumes
  it. Later sticker swaps are cancellable and use configured pricing.
- Custom renders and editable recipes are validated/stored by
  [stickers.py](../server/services/stickers.py), not trusted from iframe input.

## 4. WebSocket and activity bridge

[protocol.py](../server/protocol.py) owns envelopes, validation, limits, and close
codes. [connections.py](../server/connections.py) owns room membership and send
queues; [socket.js](../app/js/socket.js) owns client transport.

Room broadcasts are ordered by the single world process's event loop; there is
no per-room sequence protocol. A private command result matches `request_id`.
Snapshots replace room state, while events update it incrementally. Clients
request a fresh snapshot after reconnect or presence changes, including NPC
movement. Session validation remains authoritative throughout the connection.

Activity guests are same-origin iframes. The host validates origin, activity ID,
and source window before accepting bridge messages. Guest commands use the
normal server command pipeline; iframe isolation must not bypass authority.
See [host bridge](../app/js/activities.js),
[guest bridge](../activities/shared.js), and
[server bridge](../server/routes/activity_bridge.py).

## 5. Commands and gameplay boundaries

Use `.help` and [registry metadata](../server/commands/registry.py) for available
commands, [parser.py](../server/commands/parser.py) for grammar/targets, and
[handlers](../server/commands/) for permission and mutation rules. Admin console
handling is in [admin.py](../server/commands/admin.py).

Server snapshots supply gameplay quick actions. The browser may add local view
shortcuts, but it must not infer action authority from presentation.

- **Travel:** [rooms.py](../server/services/rooms.py) validates exits/locks/cards,
  persists the destination, updates presence, and closes room-bound activities.
  NPC travel uses [npc_movement.py](../server/services/npc_movement.py).
- **Card transfers:** [cards.py](../server/services/cards.py) performs atomic
  room/inventory transfers; concurrent claims cannot duplicate a stack. Pinned
  and core-card restrictions are enforced server-side. Board drop placement is
  dispatched by [drag.js](../app/js/drag.js), then validated and persisted.
- **Activities:** [activities.py](../server/services/activities.py) owns one live
  activity per account. Replacement/cancellation/travel/logout/disconnect must
  close the appropriate session. Mandatory onboarding has stronger UI gates
  than ordinary activity windows.
- **Classrooms:** [classrooms](../mods/classrooms/) owns purchase,
  customization, grade floors, materialization, and access checks. Entry shares
  the normal room-change path; persisted rooms are prepared before
  initialization/seeding.
- **Restart:** room cards, inventory, and remembered room persist; chat does not.
  See [database durability](db.md#3-world-state-db).

The `.reset_room` handler's unrestricted-access TODO remains unresolved; do not
interpret the existence of account powers as proof that reset is admin-only.

## 6. Peer audio and cutscenes

[voice.js](../app/js/voice.js) implements opt-in, gesture-unlocked push-to-talk;
[rtc.py](../server/services/rtc.py) relays signaling only between audio-enabled
connections in the same room. Media travels over WebRTC, not through gameplay
logs. Audio presence is connection-local: travel retains it, refresh/new login
does not. Offerer selection and autoplay rationale are documented in source.

Cutscenes remain available without a subsystem feature flag; reduced motion
suppresses playback. Presentation cannot determine gameplay rewards or whether
a transaction succeeded, and the server does not await playback acknowledgement.
See [cutscene authoring/contracts](cutscenes.md), including its explicit
outstanding implementation gaps, and the
[service](../server/services/cutscenes.py) /
[client manager](../app/js/cutscenes/manager.js).

## 7. Verification

[AGENTS](../AGENTS.md#testing) owns test-placement policy;
[README](../README.md#verification) owns commands. Tests cover actual browser
modules under [tests/client/](../tests/client/), server logic under
[tests/](../tests/), and minimal browser flows under
[tests/browser/](../tests/browser/). Browser tests use isolated HTTPS servers
from [fixtures.js](../tests/browser/fixtures.js).
