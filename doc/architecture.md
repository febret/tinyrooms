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
into the ignored `client/app/vendor/`.

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
has its own worldstate database. Public worlds are served under the same origin
at `/world/<instance-id>/`; nginx proxies those paths to loopback world servers
through a generated map. See the canonical
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
| Peep relationships | [vibes service](../server/services/vibes.py), [state](../server/state/vibes.py) |
| Persistence and migrations | [server/state/](../server/state/); [durability contracts](db.md) |
| Content and extensions | [server/content/](../server/content/), [mods](../server/mods.py), [behaviors](../server/behaviors/) |
| Browser rendering and state | [app/js/](../client/app/js/), [app/css/](../client/app/css/) |
| Embedded activities | [activities](../client/activities/), [client host](../client/app/js/activities.js), [server lifecycle](../server/services/activities.py) |
| MC and world management channel | [server/mission_control/](../server/mission_control/), [mission-control UI](../client/mission-control/), [mc_client](../server/mc_client.py), [mc_api](../server/mc_api.py) |

### 2.1 Content and mods

[Content loaders](../server/content/) define accepted YAML and validation.
[Shared data](../data/) supplies core tuning, cards, artwork, effects, and scenes;
[tutorial content](../worlds/tutorial/) supplies world-specific definitions.
A world may also declare an optional stylesheet (`css:` in `world.yaml`,
served at `/assets/world/<id>/world.css`) for world-specific presentation
such as cutscene scene styles.

Top-toolbar and settings icons are real SVG files served at
`/assets/ui/<key>.svg`, resolved world-first: `worlds/<id>/ui/<key>.svg`,
then each enabled mod's `ui/<key>.svg` in reverse load order, then the core
defaults under `data/ui/icons/`. Worlds and mods override a chrome icon by
dropping a same-named SVG file; the client always requests the key URL and the
server picks the winner.

[The mod loader](../server/mods.py) owns manifest discovery, enabled-mod selection,
content merging, command registration, and runtime factories. Worlds declare
`requires_mods`; startup rejects missing dependencies. The scammon-academia
world requires [classrooms](../mods/classrooms/). Mod `prepare()` runs before
world seeding so persisted dynamically materialized rooms can receive their
seeds.

Prop schema and file-wide scale settings are defined by
[prop_definitions.py](../server/content/prop_definitions.py) (re-exported through
[worlds.py](../server/content/worlds.py)). Gameplay fields — `behavior`,
`activity`, content cards, `cooldown`, and `recipes` — live on the prop
definition so every placed instance behaves identically; instances only carry
placement, custom quick actions, and optional label/description overrides.
Authored props may declare `render_kind` (`model`, `text`, `sign`,
`whiteboard`) to reuse the procedural surface renderers, and `one_per_room` to
cap placement at a single instance per room. Room owners may place
non-decorative props; `decorative` remains the marketplace/showcase flag.
Effect definitions are loaded by
[fx.py](../server/content/fx.py) and rendered by
[prop-effects.js](../client/app/js/prop-effects.js); reduced motion suppresses effects.
Props may also declare named mesh `states` and an authored `active_state`.
[rooms.py](../server/services/rooms.py) can switch a room instance's state at
runtime and broadcasts `room.prop.updated`; clients reload the active model.

The built-in sign and whiteboard are procedural surfaces. Their text/drawing is
stored by [prop_surfaces.py](../server/services/prop_surfaces.py) in the
`prop_surfaces` world table, validated by
[surface_props.py](../server/content/surface_props.py), and rendered client-side
by [surface-props.js](../client/app/js/surface-props.js) /
[surface-canvas.js](../client/app/js/surface-canvas.js). Saves broadcast
`room.prop.surface` with a monotonic revision; clients ignore stale revisions.
Whiteboard drawings are vector strokes and text, not uploaded images. The room
editor's environment allowlist includes a validated `board_image` override for
world-authored floor textures; layout updates carry the new image URL alongside
palette and tiling.

Mods may expose `start()`/`stop()` lifecycle hooks for background work. TinyTown
uses this for autonomous household NPCs while its private multi-room houses,
house purchases, visits, roommate classifieds, and community art sales live in
the `tinytown` mod. Its player-facing home is the unbound
[Tiny Mag activity](../mods/tinytown/activities/tiny-mag/), with `tinytown` and
`art-store` launch aliases, plus the separate
[Keyring activity](../mods/tinytown/activities/keyring/) (`keyring`, `keys`
aliases) for owned-home switching, lock management, and household review. Each owned home persists five roommate candidates;
adopting one adds the peep to a chosen owned home and replenishes the classified batch. Community art
is listed from an editable home whiteboard, paid at full price to the seller,
and installed as a locked whiteboard for the buyer. Only the source board stays
editable, and an owned print can be rehung for free.

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
[client API](../client/app/js/api.js) define endpoints and payloads; serializers live in
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
queues; [socket.js](../client/app/js/socket.js) owns client transport.

Room broadcasts are ordered by the single world process's event loop; there is
no per-room sequence protocol. A private command result matches `request_id`.
Snapshots replace room state, while events update it incrementally. Clients
request a fresh snapshot after reconnect or presence changes, including NPC
movement. Session validation remains authoritative throughout the connection.

Activity guests are same-origin iframes. The host validates origin, activity ID,
and source window before accepting bridge messages. Guest commands use the
normal server command pipeline; iframe isolation must not bypass authority.
Whiteboard activities save through the `activity.surface` bridge message only
after the server resolves the bound prop instance from its own activity config.
See [host bridge](../client/app/js/activities.js),
[guest bridge](../client/activities/shared.js), and
[server bridge](../server/routes/activity_bridge.py).

## 5. Commands and gameplay boundaries

Use `.help` and [registry metadata](../server/commands/registry.py) for available
commands, [parser.py](../server/commands/parser.py) for grammar/targets, and
[handlers](../server/commands/) for permission and mutation rules. Admin console
handling is in [admin.py](../server/commands/admin.py).

Server snapshots supply gameplay quick actions. The browser may add local view
shortcuts, but it must not infer action authority from presentation.

- **Travel:** [rooms.py](../server/services/rooms.py) validates exits/locks/cards,
  persists the destination, updates presence, and closes the current activity.
  NPC travel uses [npc_movement.py](../server/services/npc_movement.py).
- **Card transfers:** [cards.py](../server/services/cards.py) performs atomic
  room/inventory transfers; concurrent claims cannot duplicate a stack. Pinned
  and core-card restrictions are enforced server-side. Board drop placement is
  armed from the card's Drop action and sent on the next room click by
  [drop-targeting.js](../client/app/js/drop-targeting.js), then validated and
  persisted.
- **Activities:** [activities.py](../server/services/activities.py) owns one live
  activity per account. Replacement/cancellation/travel/logout/disconnect must
  close the appropriate session. Mandatory onboarding has stronger UI gates
  than ordinary activity windows.
- **Classrooms:** [classrooms](../mods/classrooms/) owns purchase,
  customization, grade floors, materialization, and access checks. Entry shares
  the normal room-change path; persisted rooms are prepared before
  initialization/seeding.
- **Vibes:** [vibes.py](../server/services/vibes.py) owns directed -100..100
  scores between peeps. Player-sourced rows live in the profile DB and
  NPC-sourced rows in the world DB. Occupied rooms apply the minute-based
  stinky/charisma rules through `RoomTicker` hooks; classroom lesson and
  cafeteria rules live in the classrooms mod.
- **Restart:** room cards, inventory, and remembered room persist; chat does not.
  See [database durability](db.md#3-world-state-db).

The `.reset_room` handler's unrestricted-access TODO remains unresolved; do not
interpret the existence of account powers as proof that reset is admin-only.

## 6. Interaction sounds, peer audio, and cutscenes

Interaction sounds live in `data/sounds/` and are served from
`/assets/sounds/<file>.wav`. [audio.js](../client/app/js/audio.js) decodes and
caches WAV buffers for UI clicks, room changes, cards, props, and notifications;
it no longer synthesizes tones. Content can author nested `sounds:` mappings:
props use `select`/`action`, cards use `select`/`use`, cutscenes use `start`
plus per-cue `sound`, and tasks use `started`/`completed`/`notification`.
Server loaders validate names against the library, and serializers send served
URLs. Cutscene scripts call the host `sound()` helper or rely on cue sounds;
they do not create their own audio context.

[voice.js](../client/app/js/voice.js) implements opt-in, gesture-unlocked push-to-talk;
[rtc.py](../server/services/rtc.py) relays signaling only between audio-enabled
connections in the same room. Media travels over WebRTC, not through gameplay
logs. Audio presence is connection-local: travel retains it, refresh/new login
does not. Offerer selection and autoplay rationale are documented in source.

[phone-music.js](../client/app/js/phone-music.js) is the personal Chiptune app
inside the Phone view. It drives a hidden, cross-origin chiptune.app iframe and
plays `https://chiptune.app/?play=<song>`; because the frame cannot be scripted,
track changes reload it and volume/seek are unavailable (the phone's volume keys
stay disabled). Pause works by unloading the frame. The physical-style phone
keypad drives prev/play-pause/next and star through a queue built from the
currently visible list, and previous/next friend steps cycle a highlighted
friend in the Friends app. Playback is
per-user and never changes room state. The selected track and on/off preference
are kept in browser `localStorage`. Catalog search, browse, top tracks, and
Tinyrooms community stars are proxied server-side by
[chiptune.py](../server/routes/chiptune.py) since chiptune.app sends no CORS
headers. Users star tracks into their shared profile
([chiptune_stars.py](../server/services/chiptune_stars.py)); suggestions combine
the chiptune.app top chart with tracks starred by other Tinyrooms users.
Autoplay requires one user gesture.

Cutscenes remain available without a subsystem feature flag; reduced motion
suppresses playback. Presentation cannot determine gameplay rewards or whether
a transaction succeeded, and the server does not await playback acknowledgement.
See [cutscene authoring/contracts](cutscenes.md), including its explicit
outstanding implementation gaps, and the
[service](../server/services/cutscenes.py) /
[client manager](../client/app/js/cutscenes/manager.js).

## 7. Verification

[AGENTS](../AGENTS.md#testing) owns test-placement policy;
[README](../README.md#verification) owns commands. Tests cover actual browser
modules under [tests/client/](../tests/client/), server logic under
[tests/](../tests/), and minimal browser flows under
[tests/browser/](../tests/browser/). Browser tests use isolated HTTPS servers
from [fixtures.js](../tests/browser/fixtures.js).
