# Tinyrooms — Cutscenes

Status: **implemented**. Cutscenes are always available; the only switch is the
client's reduced-motion preference (§2.3). This document is the specification; the notes
in each section marked *As built* record where the shipped code differs from it.
Related docs:
[architecture.md](./architecture.md) (current components/protocol),
[design.md](./design.md) (product/design intent),
[db.md](./db.md) (schemas), [mission-control.md](./mission-control.md) (the
other forward-looking spec).


## 1. Overview

### 1.1 What a cutscene is

A **cutscene** is a short, self-contained, scripted animation played over the
room. It is authored as ordinary HTML/CSS/JavaScript that runs *in the client
page*, inside its own container called the **cutscene frame**. Cutscene code
builds whatever it wants inside that frame: animated sprites, captions, text,
gradients, and arbitrary DOM.

The design targets the visual language of an imaginary arcade fighter: a
`movie` frame that fades in from the left on a 16:9 black stage, a `vs` frame
that slams two halves together from the top and bottom of the screen, and
similar short attack cutscenes from JRPGs.

A cutscene may show **placeholders** — images of peep stickers, cards, or
thumbnails of 3D props — as sprites inside the frame.

### 1.2 Layering contract

Cutscenes sit above the room view and the board-side panels, and **below
activity windows**. Activities are therefore never obscured by a cutscene.

```
 200  boot-guard
 100  toast-stack
  90  #global-modal-layer
  80  onboarding .activity-layer
  70  #auth-layer
  60  .chat-completions
  46  #bubble-layer
  45  .topbar
  44  #action-log
  40  .bottom-stack            <- card hand, chat, shop, editor
  37  #activity-layer          <- bumped from 36 (see §6.2)
  36  #cutscene-layer          <- new
  35  #detail-layer
  30  #panel-layer
  25  #peeps-panel
```

Because `#cutscene-layer` lives inside `.board-frame` (`app/index.html:31`) and
`.bottom-stack` is a sibling (`app/index.html:38`), the card hand, the chat
bar, the shop dock, and the editor dock are **not** covered. Chat, commands,
voice, and card play stay usable while a cutscene runs.

### 1.3 Audiences

| Audience | Delivery | Use |
| --- | --- | --- |
| `private` | Sent only to the triggering account | Flavor for a specific interaction (a prop you just used, a peep greeting you) |
| `room` | `room.event` broadcast to every occupant | Cutscene emotes, room-level events, prop/room beats |

Both audiences use the same client queue. A `room` cutscene is fire-and-forget:
clients do not synchronize, seek, or pause. Two players in the same room may
see the same room cutscene start a fraction of a second apart.

### 1.4 Non-goals

- No playback acknowledgement. The server never learns whether a cutscene
  started, finished, or was skipped. Nothing downstream (tasks, records,
  statistics, rewards) may depend on playback.
- No audio. Cutscenes are silent in this milestone.
- No persistence. Cutscene playback is never part of `room.snapshot`, so a
  client that joins mid-cutscene sees nothing.
- No cutscene editor UI. Authoring is text editing of YAML + JavaScript.
- No cutscenes under reduced motion (§2.3).

### 1.5 Trust model

Cutscene modules run in the page with full privileges — unlike activities,
which are same-origin iframes with a `sandbox` attribute
(`app/js/activities.js:199`). This is deliberate: cutscene code needs the app's
own modules (sprite helpers, prop thumbnails) and the real DOM.

The consequence is that cutscene code is **trusted content**, at the same
trust tier as world YAML and mod Python. It is never attacker-supplied:

- The module URL is resolved and signed into the play payload by the server
  from the content catalog. The client never accepts a module path from a
  cutscene message.
- Only the server's own cutscene roots are searched, with per-scene directory
  containment. *As built:* `server/routes/cutscenes.py` resolves the requested
  file under each root, requires the first path segment to equal the cutscene
  id, and skips any candidate that escapes its root. The static route is not
  feature-flagged, matching `/activities/`.
- Mods can ship cutscenes only if the operator enabled them
  (`TRSERVER_MODS`), exactly as for mod activities and mod props.

## 2. User-facing behaviour

### 2.1 Lifecycle

```
enqueue  ->  import module  ->  frame intro  ->  body  ->  frame outro  ->  teardown
```

1. **Enqueue.** A `cutscene.play` message arrives (§6). The manager appends it
   to the queue (§2.5). Nothing is rendered yet.
2. **Import.** When nothing is playing, the manager dynamically imports
   `cutscene.script_url` and calls the module's default export. Import and
   scene execution are asynchronous and never block the render loop.
3. **Frame intro.** The scene calls `beginCutscene(frameType, options)`
   (§4.2). The runtime creates the layer subtree, applies the frame type, and
   starts the frame's intro animation.
4. **Body.** The scene manipulates the stage freely. The next queued cutscene
   does not start.
5. **Frame outro.** When the scene function returns, resolves, is skipped, or
   hits the duration cap, the frame's outro animation plays.
6. **Teardown.** The layer subtree is removed, the scene's `AbortSignal`
   fires, all runtime-owned timers and animation frames are cancelled, and the
   next queued cutscene starts.

Failures never stall the queue: a failed import, a thrown scene, or a missing
frame type is logged once to the console, torn down, and the queue continues.

### 2.2 Input rules while a cutscene plays

| Surface | Behaviour |
| --- | --- |
| 3D board, prop picking, drag | Blocked (`inert`) |
| `#panel-layer` (room/emotes/inventory/journal views) | Blocked (`inert`) |
| `#detail-layer` (card and prop details) | Blocked (`inert`) |
| `#activity-layer` | **Untouched** — activities open and render above |
| `.bottom-stack` (card hand, chat, shop, editor) | Untouched and usable |
| `#bubble-layer` | Dimmed behind the frame; bubble auto-dismiss timers keep running |
| Keyboard | `Escape` skips the cutscene; focus moves to the Skip button and returns to where it was |

The `inert` sweep is shared with the existing activity focus machinery
(`syncModal` in `app/js/activities.js:45`, driven by the `MutationObserver` at
`app/js/activities.js:87`) so the two systems cannot fight over the same
attributes.

### 2.3 Reduced motion disables cutscenes entirely

When `state.ui.reducedMotion` is true — the client already normalizes
`prefers-reduced-motion` into this flag and passes it to the board
(`app/js/board.js:1117`) and to activities (`app/js/activities.js:13`) — the
manager **drops every `cutscene.play` message**:

- The cutscene layer is never created.
- No module is imported, so no network or parse cost is paid.
- One console line per session, then silence.
- No toast, no action-log line, no visual acknowledgement of any kind.

This is stricter than the rest of the client, which degrades animations
instead of removing features. A cutscene is uninterruptible by design, so the
only accessible behaviour is to not play it. The queue is not filled while
reduced motion is on, and a queue drained from before the flag flipped is
cleared when the flag flips.

The Playwright suite forces `reducedMotion: 'reduce'` for determinism, so
cutscene browser tests require a dedicated project (§9).

### 2.4 Skipping

A playing cutscene can be skipped three ways: the **Skip** button in the
frame's corner, a click/tap on the stage, or `Escape`.

Skip semantics:

- Skip aborts the body. The scene's `ctx.signal` is aborted, so
  `signal`-aware code can bail out early.
- The frame's **outro still plays** — skip is "stop the performance", not
  "teleport away". The cutscene is over within the outro duration.
- A scene that wants to forbid skipping sets `skip: false` in its definition;
  the button is then not rendered and click/Escape do nothing. The duration cap
  still applies.
- Skipping is purely local. Nothing is reported to the server.

### 2.5 Queue rules

The queue is per-client, in memory, and FIFO. It is never persisted, synced,
or shared.

| Rule | Value |
| --- | --- |
| Concurrency | Exactly one cutscene may be playing |
| Global capacity | 6 entries; a 7th is dropped and the player is told once via toast |
| Per-definition capacity | `max_queue` (default 3): the oldest queued entry for that cutscene id is dropped to make room |
| Deduplication | A new entry with the same `(cutscene id, source account id)` as an already-queued entry is dropped |
| Ordering | Strict FIFO by arrival |

Disruptions:

| Event | Behaviour |
| --- | --- |
| Room change (`.go`, `.door`, portal) | The playing cutscene finishes its outro; all queued `room_bound` cutscenes are dropped |
| Room change, non-room-bound | Survives; a private cutscene may follow the player |
| Logout | Playing outro is abandoned, queue cleared, layer removed |
| WebSocket disconnect | Same as logout |
| Session replaced | Same as logout |
| Reduced motion turned on | Queue cleared, layer removed |

Drops are silent except for the capacity toast; a dropped cutscene is flavor,
not state.

## 3. Content model

### 3.1 Definition format

Cutscene definitions are YAML, one file per source, merged in the order
core → mods → world (the same order activities use, see
`server/content/bundle.py:42` and `server/content/worlds.py:828`).

```yaml
# worlds/tutorial/cutscenes.yaml
molly-greet:
  title: Molly Greets You
  script: molly-greet.js
  frame: movie
  duration: 5200
  audience: private
  room_bound: true
  skip: true
  aliases: [greet, hello-molly]
  max_queue: 2
  params:
    stage_background: "#04141c"
    me_scale: 1.15
  text:
    - {at: 350, speaker: Molly, say: "Purrrr."}
    - {at: 2100, speaker: Molly, say: "You again? Good."}
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string | **required** | Player-facing name; used in toasts and the Action Log |
| `script` | string | `<id>.js` | Entry module, resolved inside the cutscene's own directory |
| `frame` | string | `plain` | Default frame type (§4.4) |
| `duration` | int ms | `0` | Hard cap. `0` means "no cap" and the scene must end itself; a non-zero value is the safety net for a scene that forgets |
| `audience` | `private` \| `room` \| `any` | `private` | `any` may be promoted to `room` by a launcher (§7.4) |
| `room_bound` | bool | `true` | Dropped from the queue on room change |
| `skip` | bool | `true` | Render the Skip control and honour click/Escape |
| `hidden` | bool | `false` | Exclude from the `/api/cutscenes` launch catalog; still resolvable and launchable by id (journal/system scenes) |
| `aliases` | list[string] | `[]` | Alternative ids for `.cutscene` and for card `cutscene:` references |
| `max_queue` | int | `3` | Per-definition queue capacity |
| `feature` | string | _(none)_ | Feature flag required to play; validated against `KNOWN_FEATURES` |
| `power` | string | _(none)_ | In-world power required to launch by command; validated against `POWER_NAMES` |
| `rooms` | list[string] | `[]` | Allowlist of rooms; empty means any room |
| `energy_cost` | int | `0` | Charged when launched from a command or behavior |
| `params` | mapping | `{}` | Arbitrary scalar key/value pairs handed to the scene (§4.5) |
| `text` | list[cue] | `[]` | Caption cues, convenience over `params` (§4.5) |

Cue keys: `at` (int ms from body start, **required**), `speaker` (string),
`say` (string), `style` (string, optional CSS class for the caption element).

A cue list is a shortcut, not a constraint: a scene may ignore `text`
entirely and write its own DOM, or use the cues as a starting point.

### 3.2 Directory layout and hosting

Code lives in a directory named after the cutscene id, holding its module and
any sibling assets (SVGs, sprites, CSS):

| Source | Definition file | Code root | Module URL |
| --- | --- | --- | --- |
| Core | `data/core/cutscenes.yaml` | `data/cutscenes/<id>/` | `/cutscenes/<id>/<script>` |
| Mod | `mods/<id>/content/cutscenes.yaml` | `mods/<id>/cutscenes/<id>/` | `/cutscenes/<id>/<script>` |
| World | `worlds/<world>/cutscenes.yaml` | `worlds/<world>/cutscenes/<id>/` | `/cutscenes/<id>/<script>` |

Search order for a given id mirrors the activity roots: core first, then mods
in load order, then the world. A later source that redefines an id is a **load
error**, not an override — the same rule duplicate prop ids follow. An alias
claimed by two cutscenes, or an alias equal to another cutscene's id, is also
a load error.

*As built:* the roots are assembled in `server/content/bundle.py`, which passes
core plus mod definitions into `load_world_definition` as `core_cutscenes` and
`cutscene_roots`; the world loader adds its own `cutscenes/` directory at the
front of the script search and merges `worlds/<world>/cutscenes.yaml`.

Sibling assets are ordinary same-origin URLs (`/cutscenes/<id>/sprite.svg`).
Cutscene modules may `import` them relatively, exactly as
`activities/sticker-designer/sticker-designer.js:1` imports `./parts.js`.

### 3.3 Loader validation

The loader is strict and raises `ContentError` on the first problem, matching
`server/content/activities.py:41`:

- `title` non-empty.
- `script` resolves to an existing `.js` file inside one of the search roots.
- `frame` non-empty; whether it is a *registered* frame type is a client-side
  concern (§4.4) and is deliberately not validated at load time.
- `duration` ≥ 0; `max_queue` ≥ 1; `energy_cost` ≥ 0.
- `audience` ∈ {`private`, `room`, `any`}.
- `params` is a mapping of at most 16 keys to scalars
  (str ≤ 200 chars, int, float, bool).
- `text` is a list of cues with an int `at` and at least one of `say` or
  `speaker`.
- `aliases` contains no duplicate within the definition, and no alias
  collides with another cutscene's id or alias.
- `feature` is in `KNOWN_FEATURES`; `power` is in `POWER_NAMES`; `rooms` are
  known room ids.

Cross-content validation, mirroring the activity reference check at
`server/content/worlds.py:847`:

- Every `cutscene:` reference on a card resolves (by id or alias) in the
  merged catalog.

An authored `.cutscene` command inside a prop/peep `actions:` list is not
resolved at load time. The command verb is allowlisted from the registry at
`server/services/rooms.py:206`, and an unknown id only surfaces as a runtime
"no cutscene called" message when the action fires.

### 3.4 Cutscene emotes are cards

Cutscene emotes reuse the card system end to end. A cutscene emote is a card
with `type: emote` and one extra field, `cutscene`:

```yaml
# data/cardsets/base/cards.yaml
victory-dance:
  type: emote
  cutscene: victory-dance
  label: Victory Dance
  description: A triumphant full-screen strut
  image: victory-dance.webp
  energy_cost: 5
```

Consequences:

- Ownership, stacking, packs, and the Shop are unchanged. Cutscene
  emotes are bought and traded like any other emote.
- The card still needs a static `image` (the loader requires one,
  `server/content/cards.py:96`) — a representative still, used as the card
  tile and as its thumbnail in lists.
- The card's `cutscene:` field must be added to `CardDefinition` and read by
  the loader; it is ignored for every other card type.
- An emote's category is derived from its fields, never authored: a card with
  `cutscene` is a `Cutscene` emote, a card with `animation` is an `Animation`
  emote, and everything else is an `Expression` (`server/content/cards.py`).
  The Emotes view (`app/js/views/emotes-view.js`) therefore exposes exactly
  `Expression`, `Animation`, and `Cutscene`, and the energy cost table
  `EMOTE_COSTS` (`server/services/actions.py`, `Cutscene` = 5) charges a
  cutscene emote 5 Energy; a card's explicit `energy_cost` wins.
- A cutscene emote produces **no** speech bubble. `use_emote` returns a
  cutscene result instead of a bubble result, so `.emote` on a cutscene card
  broadcasts `cutscene.play` and nothing else.
- Playing a cutscene emote costs its Energy like any other emote and produces no
  speech bubble.

## 4. Client runtime API

This is the contract cutscene authors program against.

### 4.1 Module shape

A cutscene module is an ES module served from `/cutscenes/<id>/`. It exports
one default async function, which the runtime calls once per playback:

```js
import { beginCutscene, endCutscene, sprite, wait } from "/app/js/cutscenes/stage.js";

export default async function (ctx) {
  const dom = beginCutscene("movie");
  // ... build and animate inside dom ...
  endCutscene();
}
```

Rules:

- The runtime imports the module URL from the server-provided
  `cutscene.script_url` and caches the module namespace by URL, so repeated
  playbacks of the same cutscene cost one network request for the lifetime of
  the page.
- The default export is called with a single `ctx` object (§4.3).
- Returning from the function ends the cutscene (the outro plays), as does
  calling `endCutscene()` early. A thrown error is logged once and treated as
  a normal end.
- Modules are imported by the *exact* URL the server sent. A cutscene must
  therefore not import the stage helpers through a second, differently-spelled
  URL, or it will get a second module instance with no live stage.

### 4.2 `beginCutscene(frameType, options)`

```js
const dom = beginCutscene(frameType, options) -> HTMLElement
```

Creates the cutscene layer subtree for the current playback and returns the
**root DOM node of the cutscene stage** — the element cutscene code freely
interacts with.

- `frameType` selects a frame type by name (§4.4). Unknown names fall back to
  `plain` and log once.
- `options` is the merged frame configuration (§4.5), typically
  `ctx.params.frame_options`.
- The returned element is an `<div class="cutscene-stage">`. The runtime also
  attaches two properties to it:
  - `dom.frame` — the frame element that owns the intro/outro animation.
  - `dom.root` — the layer element (the parent of the frame).
- The stage is created empty, sized by the frame's CSS, and left entirely to
  the scene. A scene that wants a full-bleed background sets it itself.
- Calling `beginCutscene` twice in one playback is a no-op that returns the
  same element.

Teardown order is the mirror image: outro, then `dom.root` removal, then
`ctx.signal` abort, then timer cleanup. A scene that keeps a reference to
`dom` after the outro is holding a detached node and must not touch it.

### 4.3 `ctx`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Cutscene id |
| `title` | string | Player-facing title |
| `frame` | string | Default frame type from the definition |
| `duration` | number | Duration cap in ms (`0` = none) |
| `skip` | boolean | Whether skipping is allowed |
| `audience` | string | `private` or `room` as actually delivered |
| `origin` | string | What launched it: `command`, `prop`, `peep`, `emote`, `behavior` |
| `source` | `{id, name}` | The triggering account, when there is one |
| `params` | object | Frozen, deep-merged key/value pairs (§4.5) |
| `text` | array | Caption cues from the definition |
| `assets` | array | Resolved placeholders (§4.6) |
| `roomId` | string \| null | The room the play event was delivered for |
| `signal` | `AbortSignal` | Aborted at teardown — after the outro — and on any early end, so `wait()` rejects and a listener can bail out |

`signal` is the only supported cancellation channel, and it aborts when the
runtime tears the layer down — which is *after* the outro, so a scene that keeps
animating during the outro still finishes. `wait()` rejects with an
`AbortError` on abort, and the runtime cancels every timer it handed out.
Anything the scene started on its own is cleaned up at teardown either way.

### 4.4 Frame types

A frame type owns the container's geometry, its intro animation, and its
outro animation. Built-ins ship in `app/js/cutscenes/frames.js` and
`app/css/cutscenes.css`:

| Frame | Look |
| --- | --- |
| `movie` | Simple 16:9 black stage that fades in from the left and fades out to the right |
| `vs` | Dramatic split versus screen; the top and bottom halves slide in from off-screen and slam together |
| `letterbox` | Full-bleed stage with animated bars pushing in from top and bottom |
| `caption` | Transparent stage with a caption bar docked to the bottom, for one-line dialogue beats |
| `plain` | No frame animation at all — a bare stage. Useful default and for debugging |

Frame options (the second argument to `beginCutscene`, and the
`params.frame_options` key):

| Option | Default | Meaning |
| --- | --- | --- |
| `from` | per frame | Edge the intro comes from: `left`, `right`, `top`, `bottom`, `center` |
| `duration` | per frame | Intro/outro length in ms |
| `background` | per frame | Stage background colour or CSS colour |
| `accent` | per frame | Secondary colour used by `vs` and `letterbox` |
| `radius` | per frame | Stage corner radius in px |

Custom frames are author-extensible. A cutscene module may register one at
top level — module top level always runs before the default export is called:

```js
import { registerCutsceneFrame } from "/app/js/cutscenes/stage.js";

registerCutsceneFrame("newspaper", {
  cssClass: "cutscene-frame-newspaper",
  introMs: 420,
  outroMs: 260,
  build(stage, options) { /* optional DOM decoration */ },
});
```

A frame descriptor provides `cssClass`, `introMs`, `outroMs`, and an optional
`build`. The runtime drives the intro/outro with a CSS animation
(`data-phase="intro" | "outro"` on the frame), so a custom frame needs only a
class with keyframes; it does not need to implement timing itself. Registrations
are global for the page, and a name may only be registered once.

### 4.5 Parameters, text, and key/value customization

`ctx.params` is a **frozen** object built by deep-merging, in order:

1. The definition's `params` block.
2. Launch-time key/value pairs supplied by the trigger (`.cutscene` arguments,
   a behavior intent, a prop/peep binding).
3. Reserved keys injected by the server: `frame_options`, `origin`,
   `source_name`, `room_id`, and `random` (a per-playback integer seed, so a
   scene can be re-randomized without `Math.random`).

Launch-time values override definition values. Unknown keys are passed through
untouched — the general key/value channel is intentionally open, so a world or
mod can parameterize frame properties, caption styling, background colours,
text, or anything else the scene understands.

Two keys are load-time reserved and may not be supplied by a trigger:
`params.frame_options` must be a mapping, and the reserved names above may
not appear in trigger arguments.

Captions have two equivalent paths:

- **Declarative.** The definition's `text` cues are in `ctx.text`. A scene can
  ignore them, or hand them to the helper: `caption(cue, options)` writes the
  cue into the frame's caption region and returns a handle with
  `element` and `hide()`. `captions(cues)` plays a whole list on the `at`
  offsets and resolves when the last one clears.
- **Imperative.** A scene can create any text DOM it likes, including
  typewriter effects and multi-line dialogue. `ctx.text` is a convenience,
  not a rendering contract.

### 4.6 Placeholders and sprites

A **placeholder** is a reference to something already in the world that a
cutscene can show as a sprite. In content, placeholders are written as
parameter values using a `$` token:

| Token | Resolves to |
| --- | --- |
| `$me` | The triggering account's sticker |
| `$user:<account id>` | Another occupant's sticker |
| `$peep:<npc id>` | An NPC peep's image |
| `$sticker:<name>` | A sticker by name |
| `$card:<stack id or card id>` | A card's art (animated art when the card has an animation) |
| `$prop:<instance id>` | A 3D prop, rendered client-side as a thumbnail |

The **server** resolves every token in a definition's `params`/`text` and in a
trigger's arguments against the current room and ships concrete asset records
in `cutscene.assets`. Tokens are matched anywhere in a string, so a caption like
`"$me, you again? Good."` contributes `$me`; a token in a caption is replaced
with the asset's `label` in the text the client receives, while `params` keeps
the raw token for `sprite()` to look up. Each record echoes the token it satisfied in `ref`, so
the scene can map a record back to the parameter that asked for it. The client
never constructs asset paths from a token.

Asset record shapes:

```json
{ "ref": "$me",  "kind": "sticker", "id": "plum", "label": "Plum",
  "url": "/assets/stickers/plum.png", "animation_url": null,
  "width": 512, "height": 512 }

{ "ref": "$card:5f2a", "kind": "card", "id": "smile", "label": "Smile",
  "url": "/assets/base/smile.webp", "animation_url": "/assets/base/wave.gif",
  "width": 512, "height": 512 }

{ "ref": "$prop:dollhouse0", "kind": "prop", "id": "dollhouse0",
  "label": "A Cute Dollhouse", "model_url": "/assets/world/tutorial/props/dollhouse.glb",
  "thumbnail": null, "scale": 1.25 }
```

`thumbnail` is `null` by design: prop thumbnails are produced in the browser
by the shared offscreen renderer (`app/js/editing/prop-thumbnails.js:50`,
already reused by the Prop Shop activity), not on the server.

Client helpers:

| Helper | Result |
| --- | --- |
| `sprite(ref, options)` | `Promise<HTMLElement>` — an `<img>` for sticker/card placeholders, a `<canvas>` with a rendered thumbnail for props, ready to append to the stage |
| `sprites(refs, options)` | `Promise<HTMLElement[]>` — the same, resolved together |
| `spriteUrl(ref)` | Synchronous URL string for stickers/cards; `""` for props |
| `asset(ref)` | The raw asset record, or `undefined` |

Every helper returns an element the scene can style freely. A prop sprite
resolves asynchronously (GLB load + render) and the runtime shows a neutral
placeholder box until then, so a scene never has to manage loading states for
sprites. Asset URLs are validated against the page origin before use; a
non-same-origin URL is rejected, logged once, and yields the placeholder box —
the same rule as `TinyActivity.image` (`activities/shared.js:29`).

If a placeholder cannot be resolved server-side, no asset record is emitted.
`sprite()` then resolves to a labelled placeholder box, so a missing sticker
degrades to a caption rather than a broken image.

### 4.7 Stage helper summary

| Export | Signature | Notes |
| --- | --- | --- |
| `beginCutscene` | `(frameType?, options?) → HTMLElement` | Creates the stage; returns its root node |
| `endCutscene` | `(result?) → void` | Ends the body early; outro still plays |
| `skipCutscene` | `() => void` | Same as a user skip; aborts `ctx.signal` |
| `wait` | `(ms) → Promise<void>` | Timer bound to `ctx.signal`; rejects on abort |
| `caption` | `(cue, options?) → {element, hide()}` | Writes one caption into the frame |
| `captions` | `(cues) => Promise<void>` | Plays a cue list on its `at` offsets |
| `sprite` / `sprites` / `spriteUrl` / `asset` | §4.6 | Placeholder resolution |
| `registerCutsceneFrame` | `(name, descriptor) → void` | Custom frames |
| `frameNames` | `() => string[]` | Registered frame types |
| `currentCutscene` | `() → object \| null` | The live `ctx`, or `null` |

## 5. Placeholders in one place

Resolving a placeholder is a **server** concern; turning a record into a
sprite is a **client** concern. The split exists so that cutscene content is
validated at load and at launch, not at paint time.

| Placeholder | Server lookup | Client rendering |
| --- | --- | --- |
| `$me` | Triggering account's sticker (`sticker_url`, as serialized in occupant payloads) | `<img>` |
| `$user:<id>` | Occupant sticker in the current room | `<img>` |
| `$peep:<id>` | NPC peep `image_url` (`server/services/rooms.py:288`) | `<img>` |
| `$sticker:<name>` | `data/stickers` or the custom sticker path (`server/app.py:1136`) | `<img>` |
| `$card:<stack or id>` | Card definition art, preferring the animation when present (`server/services/actions.py:244`) | `<img>`, animated art allowed |
| `$prop:<instance>` | Prop instance in the current room (`model_url`, `scale`, `label`) | `<canvas>` thumbnail via `prop-thumbnails.js` |

A `$prop:` or `$peep:` reference is injected automatically when a prop or peep
binding launches a cutscene, so an author can reference the interaction that
triggered the scene without naming it in YAML.

## 6. Protocol

No new WebSocket envelope type is required. Cutscenes ride the existing
`room.event` and `result.events[]` channels.

### 6.1 `cutscene.play`

```json
{ "v": 1, "type": "room.event",
  "event": {
    "type": "cutscene.play",
    "room_id": "playroom",
    "cutscene": {
      "id": "molly-greet",
      "title": "Molly Greets You",
      "script_url": "/cutscenes/molly-greet/molly-greet.js",
      "frame": "movie",
      "duration": 5200,
      "skip": true,
      "audience": "private",
      "origin": "prop",
      "source": { "id": "acct_1f", "name": "plum" },
      "params": { "stage_background": "#04141c", "me_scale": 1.15 },
      "text": [ { "at": 350, "speaker": "Molly", "say": "Purrrr." } ],
      "assets": [ { "ref": "$me", "kind": "sticker", "id": "plum",
                    "url": "/assets/stickers/plum.png" } ]
    } } }
```

The shipped payload adds three fields to the `cutscene` object:
`room_bound` (the client needs it to clear the queue on travel), `max_queue`
(the client's per-definition cap), and the `random`, `room_id`, `source_name`,
and `origin` keys inside `params` (§4.5). *As built:* the full record is built
by `CutsceneService.launch` (`server/services/cutscenes.py`).

- `room` audience: emitted as a room broadcast through the existing
  `broadcast_room_event` path (`server/broadcast.py:14`), so every occupant
  receives it and nobody else does.
- `private` audience: emitted in the triggering account's
  `CommandOutcome.private_events`, or routed out of band by
  `deliver_behavior_result` when a behavior triggers it (the event carries
  `account_id`, the same mechanism `task.updated` uses).
- The payload is a **closed** record: the client may not add fields, and the
  server will not accept a client-supplied `script_url`. Extra scene-specific
  data travels inside `params`.

### 6.2 No acknowledgement channel

There is deliberately no `cutscene.started` / `cutscene.finished` /
`cutscene.skipped` message and no client→server frame. `.cutscene` resolves
as soon as the message is queued for delivery. Any future need for playback
telemetry requires a new design, not a retrofit of this one.

### 6.3 HTTP

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/cutscenes/{id}/{file}` | The scene module and its sibling assets |
| `GET` | `/api/cutscenes` | The catalog visible to the signed-in account: `id`, `title`, `aliases`, `frame`, `audience`, `room_bound`, `rooms`, and the source. Definitions marked `hidden` (journal/system scenes such as `task-started` and `task-completed`) are omitted. Used for the `.cutscene` command palette and for tests. Never includes `script_url` |

*As built:* there is no `/cutscenes/{id}/` index route. A cutscene is a module,
not a page, so there is nothing to serve; the runtime never loads HTML. The two
routes live in `server/routes/cutscenes.py` and are mounted with
`app.include_router(cutscene_routes.router)` in `server/app.py`. `/api/cutscenes`
requires a session (401 otherwise) and filters by the account's remembered
room. The command palette is fed by the server-provided `.help` catalog rather
than by this route.

Route rules: search the cutscene roots in the order of §3.2, confine every
resolved path to the matched `cutscenes/<id>/` directory (404 on escape,
mirroring `_safe_path`), guess MIME types as the activity routes do, and
return 404 with a plain diagnostic page for an unknown id.

The static route is **not** feature-flagged, matching the existing behaviour
for `/activities/`. The flag gates *playback*, not delivery of inert files.

## 7. Server design

### 7.1 Modules

| Path | Responsibility |
| --- | --- |
| `server/content/cutscenes.py` | `CutsceneDefinition`, `CutsceneCatalog`, strict loader, merge, validation |
| `server/services/cutscenes.py` | Resolution by id/alias, launch decisions, placeholder resolution, energy, payload building |
| `server/commands/cutscenes.py` | `.cutscene` handler |
| `server/content/cards.py` | `cutscene` field on `CardDefinition` (one new field) |
| `server/services/actions.py` | `use_emote` cutscene branch; `Cutscene` in `EMOTE_COSTS` |
| `server/content/bundle.py`, `server/content/worlds.py`, `server/mods.py` | Loading, merging, cross-content validation, world reload |
| `server/routes/cutscenes.py` | `/cutscenes/{id}/{file}` and `/api/cutscenes` routes |
| `server/app.py` | Service construction, router mount, command registration |
| `server/behaviors/context.py`, `server/behaviors/dispatcher.py` | `cutscene` intent |

`CutsceneDefinition` is a frozen dataclass in the shape of `ActivityDefinition`
(`server/content/activities.py:12`): `id`, `title`, `script_name`, `frame`,
`duration_ms`, `audience`, `room_bound`, `skip`, `hidden`, `aliases`, `max_queue`,
`required_feature`, `power`, `rooms`, `energy_cost`, `params`, `text`,
`source`, and the resolved `script_url`.

The catalog is loaded once with the world bundle, so a world reload
(`RuntimeState._apply_world_reload`) picks up cutscene edits exactly as it does
for activities.

### 7.2 Availability

Cutscenes have **no server-side feature flag**. The subsystem, the `.cutscene`
command, `.cutscene` quick actions on props and peeps, cutscene emote cards, and
the behavior intent are always live, so nothing about a world changes when an
operator edits `TRSERVER_FEATURES`. The only availability switch is the
client's reduced-motion preference (§2.3), which drops play messages.

A single scene can still be gated on its own flag with `feature:` in its
definition, exactly as an activity definition can. The gate is checked per
launch by `CutsceneService.check`, and the value is validated against
`KNOWN_FEATURES` at load time, so a typo is a `ContentError` rather than a
scene that silently never plays.

### 7.3 Launch resolution

A launch attempt resolves, in order: the definition by id or alias → the
definition's `feature`/`rooms`/`power` gates → energy → the audience decision →
placeholder resolution → payload build. Any failure is a `CommandError` with a
player-facing message, exactly as `start_activity` does
(`server/commands/activity_launch.py:63`).

Placeholder resolution happens *at launch*, against the current room. A
`$user:` that is not present, a `$prop:` from another room, or a `$card:` the
account does not own yields no asset record; it never fails the launch. Scenes
must be written to tolerate missing sprites (§4.6).

### 7.4 The `.cutscene` command

```
.cutscene <id|alias> [@prop:<instance> | @peep:<id>] [key=value ...] [--room] [--private]
```

- No power is required to launch a `private` cutscene: playing a cutscene for
  yourself is flavor, and the definitions that matter are reachable through
  props, peeps, and emotes anyway. A definition may set `power:` to restrict
  itself; the check happens in the handler because registry powers are
  per-command, not per-definition.
- `--room` promotes the delivery to the room and requires the definition to be
  `room` or `any`. `--private` forces private delivery.
- `key=value` pairs become launch-time params (§4.5). Values are scalars, at
  most 16 pairs; they are truncated to the same limits as definition params.
- A `@prop:`/`@peep:` target injects the corresponding placeholder and sets
  `origin` to `prop`/`peep`.
- The command is quiet by default (`toast=False`): the Action Log gets one
  line, the player gets no toast, because the cutscene is the feedback.

### 7.5 Trigger bindings

**Props and peeps.** A prop instance or peep definition exposes a cutscene the
same way it exposes any other action: an entry in its `actions:` list.

```yaml
molly:
  actions:
    - ["Greet", ".cutscene molly-greet @peep:molly"]
```

There is no implicit binding: the author names the cutscene and the `@peep:` /
`@prop:` target explicitly. The entry is normalized like any authored action,
so it appears only when the `.cutscene` verb is registered and the environment
allows it, and it keeps the author's placement and label. The target is what
makes the scene resolve that entity's placeholder asset and sets `origin` to
`peep`/`prop`; without it the scene still plays, but `origin` stays `command`.

**Behaviors.** A new intent:

```python
context.cutscene("molly-greet", audience=None, params=None, room_bound=None)
```

It resolves the definition, applies defaults, and emits a `cutscene.play`
event. `audience` defaults to `private` and, for a behavior, means "the
account whose action triggered this event" — routed with `account_id` set so
`deliver_behavior_result` reaches exactly that player. Room-wide behavior
cutscenes set `audience="room"` and are added to
`BehaviorResult.room_broadcasts`. Unresolvable ids are recorded in
`BehaviorResult.rejected` rather than raising, because one bad script must
never break the room loop (`server/behaviors/dispatcher.py:261`). *As built:*
`_apply_cutscene` catches every failure — unknown id, disabled flag, missing
account — logs it, and adds nothing to the result, so a bad script produces
silence rather than a broken room.

**Emotes.** `.emote` on a card with a `cutscene:` field takes the cutscene
branch. The room is notified via a single `cutscene.play` broadcast; no
bubble, no inventory mutation. The Action Log line is the standard
"… used …" message.

## 8. Client architecture

### 8.1 Modules

| Path | Responsibility |
| --- | --- |
| `app/js/cutscenes/manager.js` | Queue, playback state machine, layer lifecycle, input gating, reduced-motion kill switch, module cache |
| `app/js/cutscenes/stage.js` | The singleton stage API (§4.7) and the frame registry |
| `app/js/cutscenes/frames.js` | Built-in frame descriptors |
| `app/js/cutscenes/placeholders.js` | Asset record → element, prop thumbnails, origin validation, element cache |
| `app/js/inert.js` | The board-side `inert` sweep, shared by the render loop and the cutscene manager |
| `app/css/cutscenes.css` | Layer, frame geometry, keyframes, Skip control |
| `app/js/views/emotes-view.js` | Category list is `Expression`, `Animation`, `Cutscene` |

*As built:* the `inert` sweep moved out of `app/js/ui.js` into `app/js/inert.js`
rather than being written by the manager. Both `server/app.py` and
`app/js/ui.js` were already within a few lines of the 1200-line rule, so the
sweep and the two new route handlers were extracted rather than appended.

Every file stays under the 1200-line rule enforced by
`tests/test_ui_presentation.py:67`.

### 8.2 DOM and CSS

`app/index.html` gains one element and one stylesheet:

```html
<link rel="stylesheet" href="/app/css/cutscenes.css">
...
<div id="board-overlay" class="board-overlay" aria-live="polite"></div>
<div id="cutscene-layer" class="cutscene-layer"></div>
<div id="activity-layer" class="activity-layer"></div>
```

The cutscene layer is inserted **after** `#board-overlay` and **before**
`#activity-layer`, and `.activity-layer` moves from `z-index: 36` to `37` in
`app/css/main.css:130` and `app/css/activities.css:4` so activities keep
winning. The layer is `pointer-events: none` while empty and `auto` only while
a cutscene plays, and it is `inset: 0` (unlike the activity layer, it does not
avoid the card-hand tray — the tray is outside `.board-frame` anyway).

Runtime DOM shape:

```html
<div id="cutscene-layer" class="cutscene-layer" data-state="playing" data-blocking="1">
  <div class="cutscene-root" data-cutscene="molly-greet" data-state="playing">
    <div class="cutscene-frame cutscene-frame-movie" data-phase="intro" data-from="left"
         data-cutscene="molly-greet" role="dialog" aria-label="Molly Greets You">
      <div class="cutscene-stage" data-cutscene-stage="molly-greet"> ...scene DOM... </div>
      <div class="cutscene-captions"></div>
      <button class="cutscene-skip" type="button">Skip</button>
    </div>
  </div>
</div>
```

`data-state` (`idle` | `loading` | `playing` | `outro`) and `data-phase`
(`intro` | `body` | `outro`) are the only state the tests and CSS need; the
manager is never inspected from outside.

### 8.3 Store integration

`cutscene.play` never reaches the store. The queue is imperative and timed,
and a playing cutscene is not a snapshot-worthy fact. `ui.js` intercepts the
event type in the socket callbacks and handles it out of band, filtering it out
of the dispatch:

1. In `onRoomEvent`, intercept `cutscene.play` before the `room-event`
   dispatch and call `cutscenes.enqueue(event)`.
2. In `onResult`, intercept `cutscene.play` inside `envelope.events` — that is
   how `private` cutscenes arrive — and remove it from the events array handed
   to the store.
3. `applyServerEvent` in `app/js/state.js` therefore has no `cutscene.play`
   branch, and `room.snapshot` is unaffected.

Nothing in the render path awaits cutscene work, so the module import can
never delay board rendering.

Room change, logout, and disconnect are signalled to the manager from the same
place: the room identity carried by the store (`data-auth` on `#app`, and the
room id in state) plus the socket status callback. A disconnect already
surfaces through `onStatus`, so the manager needs no new plumbing for it.

### 8.4 Accessibility

- The frame is `role="dialog"` with `aria-label` set to the cutscene title.
- Focus moves to the Skip button when playback starts and returns to the
  previously focused element at teardown.
- `Escape` skips, and a keydown listener is active only while playing.
- Because the layer covers the board, the board canvas, `#board-overlay`,
  `#panel-layer`, and `#detail-layer` are made `inert` for the duration and
  released at teardown, including on abnormal teardown paths. The manager does
  not write `inert` itself: it toggles a `cutscene-playing` class on `#app` and
  asks the render loop's sweep (`app/js/inert.js`) to re-apply, so there is
  exactly one writer and the activity layer's `inert` observer never sees a tug
  of war.
- Focus is **not** trapped. Trapping would contradict §2.2: the chat bar has to
  stay reachable. Nothing interactive sits behind the cutscene except the
  card hand, chat, shop, and editor dock, which stay live on purpose.
- Nothing is announced to screen readers beyond the dialog label. Cutscene
  captions are decorative visuals; the same information is expected to exist
  in chat or the Action Log.

## 9. Worked example

A complete, shippable pair. This is the reference implementation for authors.

### 9.1 A private prop/peep cutscene (`movie` frame)

`worlds/tutorial/cutscenes.yaml`:

```yaml
molly-greet:
  title: Molly Greets You
  script: molly-greet.js
  frame: movie
  duration: 5200
  audience: private
  room_bound: true
  aliases: [greet]
  params:
    stage_background: "#04141c"
    caption_color: "#f7f5ed"
  text:
    - {at: 350, speaker: Molly, say: "Purrrr."}
    - {at: 2100, speaker: Molly, say: "$me, you again? Good."}
```

`worlds/tutorial/cutscenes/molly-greet/molly-greet.js`:

```js
import {
  beginCutscene, endCutscene, sprite, wait, captions,
} from "/app/js/cutscenes/stage.js";

const HEART_GLYPHS = ["❤️", "💖", "💕", "💗", "💓", "💞"];
const DEFAULT_PEEP = "$peep:molly";

function burstHearts(dom, count = 20) {
  const burst = document.createElement("div");
  burst.className = "cutscene-hearts";
  for (let index = 0; index < count; index += 1) {
    const heart = document.createElement("span");
    heart.className = "cutscene-heart";
    heart.textContent = HEART_GLYPHS[index % HEART_GLYPHS.length];
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
    const distance = 26 + (index % 4) * 7;
    heart.style.setProperty("--heart-x", `${(Math.cos(angle) * distance).toFixed(2)}vmin`);
    heart.style.setProperty("--heart-y", `${(Math.sin(angle) * distance).toFixed(2)}vmin`);
    heart.style.setProperty("--heart-delay", `${(index % 5) * 45}ms`);
    heart.style.setProperty("--heart-scale", `${(0.85 + (index % 4) * 0.2).toFixed(2)}`);
    heart.style.setProperty("--heart-rotate", `${(index % 2 ? 1 : -1) * 18}deg`);
    burst.append(heart);
  }
  dom.append(burst);
  return burst;
}

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    duration: 700,
  });

  const couple = document.createElement("div");
  couple.className = "cutscene-couple";

  const me = await sprite("$me");
  me.className = "cutscene-sprite cutscene-sprite-me";

  const peepRef = typeof ctx.params.peep === "string" ? ctx.params.peep : DEFAULT_PEEP;
  const peep = await sprite(peepRef, { label: "Molly" });
  peep.className = "cutscene-sprite cutscene-sprite-peep";

  couple.append(me, peep);
  dom.append(couple);

  const line = document.createElement("p");
  line.className = "cutscene-line";
  line.style.color = ctx.params.caption_color || "#f7f5ed";
  line.textContent = `${ctx.params.source_name || "Someone"} steps closer.`;
  dom.append(line);

  await wait(1200);
  line.remove();

  couple.classList.add("cutscene-couple-meet");
  await wait(760);
  burstHearts(dom);

  await captions(ctx.text);
  await wait(400);
  endCutscene();
}
```

Wired up with a Greet entry in the `molly` peep's `actions:` list in
`worlds/tutorial/peeps/peeps.yaml` (`["Greet", ".cutscene molly-greet @peep:molly"]`),
which gives the Playroom's Molly the **Greet** quick action.
Energy is not charged because the definition sets none; the scene is pure
flavor and is discarded on room change. The second cue shows the caption token
rule: `$me` in a `say` string reaches the client as the player's display name,
and the sticker itself is still available through `sprite("$me")`.

The scene also shows a peep placeholder. The Greet action's `@peep:molly`
target becomes the `peep` param, so `sprite(ctx.params.peep)` resolves Molly's
own sticker through the same mechanism; when no target is given the scene falls
back to `$peep:molly`. The two sprites sit in a `.cutscene-couple`; adding the
`cutscene-couple-meet` class plays the approach keyframes, and `burstHearts`
scatters `.cutscene-heart` spans whose per-element custom properties drive one
radial keyframe each (see `app/css/cutscenes.css`).

### 9.2 A room-wide cutscene emote (`vs` frame)

`worlds/tutorial/cards/cards.yaml` (and `victory-dance` added to
`worlds/tutorial/cards/pack.yaml`, so the tutorial pack can drop it):

```yaml
victory-dance:
  label: Victory Dance
  description: A triumphant full-screen strut. Plays for the whole room.
  image: victory-dance.png
  type: emote
  cutscene: victory-dance
  rarity: Uncommon
  energy_cost: 5
```

*As built:* the card lives in the tutorial cardset rather than the base one. The
base pack is asserted to contain only Common cards, so a scene emote does not
belong there.

`data/core/cutscenes.yaml`:

```yaml
victory-dance:
  title: Victory Dance
  script: victory-dance.js
  frame: vs
  duration: 4200
  audience: room
  room_bound: false
  max_queue: 1
  params:
    accent: "#f0b429"
    stage_background: "#120a24"
```

`data/cutscenes/victory-dance/victory-dance.js`:

```js
import { beginCutscene, endCutscene, sprite, wait, registerCutsceneFrame } from "/app/js/cutscenes/stage.js";

registerCutsceneFrame("victory-banner", {
  cssClass: "cutscene-frame-victory",
  introMs: 520,
  outroMs: 300,
});

export default async function (ctx) {
  const dom = beginCutscene("victory-banner", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
  });

  const banner = document.createElement("h2");
  banner.className = "cutscene-banner";
  banner.textContent = ctx.title.toUpperCase();
  dom.append(banner);

  const dancer = await sprite("$me");
  dancer.className = "cutscene-dancer";
  dom.append(dancer);

  await wait(2600);
  endCutscene();
}
```

Anyone who opens the tutorial pack can play it with `.emote`; it plays for the
whole room and is not room-bound, so it survives travel. Every occupant queues
it locally and plays it in arrival order, with no synchronization.

`victory-banner` is the worked example of an author-defined frame: the module
registers it at top level, before its default export is called, and
`app/css/cutscenes.css` carries the matching `.cutscene-frame-victory` keyframes.
A frame name registered twice is ignored after the first registration.

## 10. Testing strategy

### 10.1 Python

`tests/test_cutscenes.py`, following `tests/test_milestone3_activities.py`:

- Loader: required `title`, existing `script`, scalar `params`, well-formed
  `text` cues, valid `audience`/`feature`/`power`/`rooms`, alias collisions,
  duplicate ids across sources.
- Cross-content: a card naming a missing cutscene is a `ContentError`; an
  authored `.cutscene` action on a prop or peep serializes with its label.
- Service: resolution by id and alias, `rooms` allowlist, `power` requirement,
  energy charging, audience promotion via `--room` for `private` definitions.
- Placeholders: `$me`, `$user:`, `$peep:`, `$sticker:`, `$card:`, `$prop:`
  resolution; missing references produce no asset record and do not fail the
  launch; cross-room `$prop:` is ignored.
- Protocol: `room` cutscenes reach every occupant and no one else; `private`
  cutscenes reach only the actor; the payload contains a server-resolved
  `script_url` and the merged params.
- Emote integration: a cutscene card is stackable, `.emote` broadcasts
  `cutscene.play` with `origin: "emote"`, charges Energy, and produces no
  bubble.
- Availability: `.cutscene` is always registered, the service needs no enabled
  features, and a definition-level `feature:` gate is what rejects a launch.
- Behavior intent: private routing reaches only the triggering account, room
  routing reaches the room, an unresolvable id and a disabled feature produce
  nothing and no error.

*As built:* 71 tests. Behavior coverage dispatches a real `tick` event through
`BehaviorDispatcher` with an in-memory script rather than calling the intent
applier directly, so the whole path is exercised.

### 10.2 Browser

`playwright.config.js` currently forces `reducedMotion: 'reduce'`, which
disables cutscenes entirely (§2.3). A third project is therefore required:

| Project | Viewport | Motion | Runs |
| --- | --- | --- | --- |
| `desktop` | 1280×800 | reduce | everything existing |
| `portrait` | 390×844 touch | reduce | everything existing |
| `desktop-motion` | 1280×800 | `no-preference` | `cutscenes.spec.js` only |

`tests/browser/cutscenes.spec.js` (1 test, `desktop-motion` only):

- `.cutscene` plays, the frame and stage appear, and the layer is torn down.

Cutscene *behavior* beyond real playback is covered by the Python suite
(`tests/test_cutscenes.py`): commands, audience, placeholders, captions, emote
targeting, room changes, pack-open, and unknown-id rejection. Under
`reducedMotion: 'reduce'` the default projects run one case in `flows.spec.js`
asserting a `cutscene.play` never creates the layer.

*Still to do:* visual snapshots. The Emotes panel gains the `Cutscene` category
tab, so `emotes.png` needs a deliberate baseline review and re-record once the
pre-existing screenshot failures in `screenshots.spec.js` are resolved. Frame
captures (`movie`, `vs`) should be added at the same time.

### 10.3 Performance and static checks

- `tests/browser/perf/dom-counters.js` gains a cutscene counter; the perf
  budget records the layer's node count at peak so a runaway scene is visible.
- `npm run test:perf` must show no regression; the cutscene tier is only
  meaningful once at least one real scene ships.
- `tests/test_ui_presentation.py` covers the new stylesheet link, the
  `index.html` landmarks, and the 1200-line rule for the new modules.

## 11. As built

The feature shipped in four phases. This is the file map that resulted, for
anyone extending it.

### Server

| File | Role |
| --- | --- |
| `server/config.py` | `AppConfig.cutscenes_path` (no feature flag) |
| `server/content/cutscenes.py` | `CutsceneDefinition`, `CutsceneCue`, `CutsceneCatalog`, strict loader, merge, `parse_param_arguments`, `resolve_cutscene_id` |
| `server/content/bundle.py` | Loads `data/core/cutscenes.yaml` and mod catalogs, passes them and the script roots into the world loader |
| `server/content/worlds.py` | `cutscenes` on `WorldDefinition`; resolves definitions and validates card `cutscene:` references |
| `server/mods.py` | `ModDefinition.cutscenes_path`, `LoadedMods.cutscene_definitions` / `cutscene_roots()` |
| `server/services/cutscenes.py` | `CutsceneService` (catalog, resolve, check, audience, launch, placeholder resolution, per-definition `feature_enabled`, `valid_stickers`), `CutsceneLaunch`, `choose_audience`, `CutsceneError` |
| `server/commands/cutscenes.py` | `cutscene_command` plus the shared launch/resolve/deliver helpers used by the emote path. Deliberately does not import `server.commands.core` (the registry imports it) |
| `server/commands/core.py` | Registers `.cutscene` with `toast=False`, like `.emote` and `.talk` |
| `server/commands/gameplay.py` | `play_cutscene_emote`, the `use_emote` cutscene branch entry point |
| `server/services/actions.py` | `ActionResult.cutscene`, the `use_emote` branch, `Cutscene` in `EMOTE_COSTS` |
| `server/content/cards.py` | `cutscene` field on `CardDefinition`, emote-only validation, `cutscene_card_references` |
| `server/services/cards.py` | `cutscene` in the serialized definition, plus `asset_urls`/`has_definition` used by placeholder resolution |
| `server/services/rooms.py` | Serializes authored prop/peep quick actions, including `.cutscene` entries |
| `server/behaviors/context.py`, `dispatcher.py` | `context.cutscene(...)` intent and `_apply_cutscene` |
| `server/routes/cutscenes.py` | `/cutscenes/{id}/{file}` and `/api/cutscenes` |
| `server/routes/html_pages.py` | The activity fallback page, moved out of `app.py` for the line limit |
| `server/commands/context.py` | `cutscenes` on `CommandContext`; the sticker set now comes from the service instead of a per-command directory scan |

### Client

| File | Role |
| --- | --- |
| `app/js/cutscenes/manager.js` | Queue, playback state machine, module cache, layer lifecycle, focus, reduced-motion kill switch, room/sign-out/transport reactions |
| `app/js/cutscenes/stage.js` | The authoring API (`beginCutscene`, `endCutscene`, `skipCutscene`, `wait`, `caption`, `captions`, `sprite`, `sprites`, `spriteUrl`, `asset`, `registerCutsceneFrame`, `frameNames`, `currentCutscene`) and the playback session |
| `app/js/cutscenes/frames.js` | The five built-in frame descriptors |
| `app/js/cutscenes/placeholders.js` | Asset record → `<img>`/`<canvas>`, prop thumbnails, origin validation, element cache |
| `app/js/inert.js` | The board-side `inert` sweep, shared by render and the cutscene manager |
| `app/css/cutscenes.css` | Layer, five frame geometries plus the `victory-banner` example, keyframes, sprite and caption styles |
| `app/js/ui.js`, `app/js/state.js`, `app/js/commands.js`, `app/js/views/emotes-view.js` | Layer element, out-of-band event interception, palette entry, `Cutscene` category, `cutscene` on normalized cards |
| `app/index.html`, `app/css/main.css`, `app/css/activities.css` | Stylesheet link, `#cutscene-layer`, activity layer bumped to `z-index: 37` |

### Content shipped

`data/core/cutscenes.yaml` + `data/cutscenes/victory-dance/`,
`worlds/tutorial/cutscenes.yaml` + `worlds/tutorial/cutscenes/molly-greet/`,
the `victory-dance` card in `worlds/tutorial/cards/` (art and pack entry), and
Molly's Greet `.cutscene` action.

### Tests

`tests/test_cutscenes.py` (71), `tests/browser/cutscenes.spec.js` (10), one
reduced-motion case in `tests/browser/flows.spec.js`, and
`tests/browser/helpers.js:grantCardAsAdmin` for the emote flow.

## 12. Open questions and deliberate deferrals

| Item | Status |
| --- | --- |
| Audio in cutscenes | Deferred. The frame API has no sound hook and scenes must not create their own `AudioContext`; revisiting this means designing a cutscene-specific sound budget |
| Playback acknowledgement | Deferred by decision (§1.4). Any future telemetry needs a new design, not this contract |
| Cutscene state in snapshots | Deferred. A late joiner misses the current cutscene, which is acceptable for 2–6 second scenes |
| Cross-client synchronization | Not supported and not planned. Scenes are local playback of a broadcast |
| Cutscene authoring UI | Out of scope. Authoring is YAML + JavaScript under version control |
| `world-editor` cutscene authoring | Would require the world editor (`server/routes/world_editor.py`) to gain a cutscene editor; noted, not planned |
| Custom frame CSS shipped by content | Deferred. Custom frames are registered in JavaScript; per-scene CSS files are a possible later addition to the hosting rules |
| Queue persistence across reload | Not supported. A page reload clears the queue |
| Cutscene-aware visual baselines | Outstanding. The Emotes panel gains a fourth tab, so `emotes.png` needs a deliberate re-record; frame captures (`movie`, `vs`) should land at the same time. See §10.2 |
| Cutscene node counter in the perf suite | Outstanding. `tests/browser/perf/dom-counters.js` has no cutscene counter yet, so a runaway scene would not show up as a budget regression |
