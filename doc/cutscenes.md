# Tinyrooms — Cutscenes

Status: **implemented, with outstanding contract gaps** (§8). Cutscenes are
always available; the client's reduced-motion preference disables playback.
This document retains authoring guidance and design requirements. Source links
describe the shipped implementation; requirements marked outstanding are not
claims that the code already satisfies them.

Related: [architecture](./architecture.md), [design intent](./design.md),
[persistence](./db.md). For exact fields, defaults, and validation, follow the
[source map](#7-source-map-and-verification) rather than copied inventories.

## 1. Overview

### 1.1 What a cutscene is

A **cutscene** is a short, self-contained, scripted animation played over the
room. It is ordinary HTML/CSS/JavaScript running *in the client page*, inside
its own **cutscene frame**. It may build animated sprites, captions, gradients,
and arbitrary DOM within that frame.

The visual language is an imaginary arcade fighter: a `movie` frame fading in
from the left on a 16:9 black stage, a `vs` frame slamming two halves together,
and short JRPG attack animations. Peep stickers, card art, and prop thumbnails
can serve as sprites without duplicating world assets.

### 1.2 Layering contract

Cutscenes cover the board and board-side panels but sit **below activities**.
Activities must never be obscured by a cutscene. The card hand, chat bar, shop,
and editor dock are outside `.board-frame` and remain usable; chat, commands,
voice, and card play continue during playback.

The actual landmarks and stacking rules are in [index.html](../app/index.html),
[cutscene CSS](../app/css/cutscenes.css), [main CSS](../app/css/main.css), and
[activity CSS](../app/css/activities.css). Keep this relationship when changing
stacking contexts rather than treating a copied z-index inventory as authority.

### 1.3 Audiences

| Audience | Delivery | Use |
| --- | --- | --- |
| `private` | Triggering account only | Personal interaction flavor, a greeting, a reward presentation |
| `room` | Room broadcast | Emotes, room events, prop/room beats |

Both use the same local queue. A room cutscene is fire-and-forget: clients do
not synchronize, seek, or pause, and may start at slightly different times.

### 1.4 Presentation, not game state

There is **no playback acknowledgement**. The server never learns whether a
scene started, finished, or was skipped. Tasks, records, statistics, inventory,
and rewards must not depend on playback. `.cutscene` resolves when delivery is
queued, not when the scene finishes. Future telemetry requires a new design.

Playback is absent from `room.snapshot`; late joiners miss the current scene.
The queue is not durable. Authoring is YAML + JavaScript under version control,
not an editor UI. Scenes are silent in this milestone and do not run under
reduced motion.

For reward/reveal flows, commit the authoritative result independently, then
present it. The shipped [pack-open scene](../data/cutscenes/pack-open/pack-open.js)
is presentation of an already-decided draw. The [command path](../server/commands/gameplay.py)
and [UI fallback](../app/js/ui.js) keep reduced-motion and replayed opens usable
through an inline reveal. Skipping or losing a scene must never lose a reward.

### 1.5 Trust model

Cutscene modules have full page privileges. Unlike sandboxed activity iframes,
they need the app's modules, sprite helpers, prop thumbnails, and real DOM.
They are **trusted content**, at the same trust tier as world YAML and mod
Python, never attacker-supplied scripts.

- The server resolves the module from its content catalog and publishes
  `script_url` in the play payload. This is server-selected, not a cryptographic
  signature. Launch arguments cannot select an arbitrary module URL.
- The client imports that server-provided URL. It does not independently map
  an id to a module path; preserving the trusted delivery boundary is essential.
- Only configured core/world/enabled-mod roots are served. The
  [static route](../server/routes/cutscenes.py) resolves candidates, rejects root
  escapes, and requires the first contained segment to match the scene id.
- Mods contribute scripts only when enabled by the operator (`TRSERVER_MODS`).
- Static delivery is not feature-flagged, like `/activities/`. A definition's
  optional `feature:` gate controls launches, not inert file delivery.

## 2. User-facing behaviour

### 2.1 Lifecycle

The intended lifecycle is:

```
enqueue -> import module -> frame intro -> body -> frame outro -> teardown
```

1. A `cutscene.play` event enters the local FIFO; nothing starts concurrently.
2. The manager imports the scene asynchronously and caches its module by URL.
   Scene work must not block the render loop.
3. The scene calls `beginCutscene(frameType, options)` to configure its stage.
4. The body manipulates that stage; the next queued scene waits.
5. Return/resolution, explicit end, skip, or the duration cap should end the
   body and play the outro.
6. Teardown removes the layer subtree, cancels runtime-owned work, releases
   input blocking, restores focus, and advances the queue.

Failed imports, thrown scenes, and unknown frames must not stall the queue.
Unknown frames fall back to `plain`. **Completion/rejection handling and
cancellation timing are not fully implemented**; see §8 before relying on
automatic return or a cap as the only way to end an authored scene.

The [manager](../app/js/cutscenes/manager.js) currently builds the skeleton
before import, runs its intro phase before calling the scene, and lets
`beginCutscene` configure the prepared stage. This differs from the original
scene-driven intro description; do not infer timing guarantees from the
diagram beyond the intended phases.

### 2.2 Input and accessibility

| Surface | Contract |
| --- | --- |
| 3D board, prop picking, drag | Blocked during playback |
| `#panel-layer` | Blocked (`inert`) |
| `#detail-layer` | Blocked (`inert`) |
| `#activity-layer` | Untouched and above the scene |
| `.bottom-stack` | Card hand, chat, shop, and editor remain usable |
| Speech bubbles | Behind the frame; their dismiss timers continue |
| Keyboard | Escape skips when allowed; focus moves to Skip and returns at teardown |

The frame has `role="dialog"` and an `aria-label` containing its title.
**Focus is not trapped**: a trap would prevent reaching chat and the live docks.
Captions are decorative; essential information must also exist in chat, the
Action Log, or the relevant gameplay UI. No additional screen-reader
announcement is required beyond the dialog label.

The manager toggles `cutscene-playing` on `#app` and asks the shared
[inert sweep](../app/js/inert.js) to reapply. It must not compete with the
[activity focus machinery](../app/js/activities.js) for the same attributes.
Release blocking on abnormal teardown as well as ordinary completion.

The original contract also names `#board-overlay` as inert during playback;
the current sweep explicitly targets the canvas and panel/detail layers, not
that overlay. Preserve the input-blocking requirement when reconciling it.

### 2.3 Reduced motion disables cutscenes entirely

When `state.ui.reducedMotion` is true, the manager drops every play event:

- No scene subtree is rendered and no scene module imported for that event.
- The queue is not filled.
- One console warning per manager lifetime, then silence for this condition.
- No toast, Action Log entry, or visual acknowledgement of suppression.

This is stricter than degrading animations elsewhere: cutscenes are optional
visual interruptions, so the accessible option is to omit them entirely.
Turning reduced motion on must also clear pending entries and remove active
presentation. Manager-state cleanup on that transition remains incomplete
(§8); hiding DOM is not sufficient if subsequent playback cannot advance.

The ordinary browser projects force reduced motion for determinism. Real
playback therefore has its own `desktop-motion` project (§7).

### 2.4 Skipping

The Skip button, stage click/tap, and Escape request a local skip. No skip
message goes to the server. With `skip: false`, the control is hidden and
click/Escape do nothing; a configured duration cap **must still apply**.

The intended semantics are to abort the body through `ctx.signal`, then play
the outro: skip means “stop the performance,” not “teleport away.” The cutscene
should be over within the outro duration. The current manager delays the
signal until teardown and uses its skip-controlled stop for the cap (§8).
Those are outstanding gaps, not permission for unbounded non-skippable scenes.

### 2.5 Queue and disruptions

The queue is per-client, in-memory FIFO, never persisted or shared.

| Rule | Value |
| --- | --- |
| Concurrency | One active playback |
| Global capacity | Six pending entries; reject the next, with one capacity toast |
| Per-definition capacity | `max_queue`, default three; discard oldest pending entry for that id |
| Deduplication | Drop an entry matching a pending `(scene id, source account id)` |
| Ordering | Arrival order after these drops |

The current manager implements the pending-entry rules, but authored
`max_queue` never reaches it in the launch payload (§8), so ordinary launches
use the default. The active entry is not part of the pending queue or its
deduplication check. Drops may be logged; only capacity overflow needs
player-facing feedback because a dropped scene is flavor, not state.

Intended disruption behaviour:

| Event | Requirement |
| --- | --- |
| Room change | End active room-bound presentation through its outro; drop queued room-bound entries |
| Non-room-bound scene | May follow the player across rooms |
| Logout, disconnect, session replacement | Abandon active outro, clear queue, remove layer |
| Reduced motion enabled | Clear queue and remove presentation entirely |

The current room-change path drops pending room-bound entries but does not
end the active scene. Logout/disconnect abandonment also has a settled/outro
edge case. These requirements remain outstanding (§8).

## 3. Content model

### 3.1 Definition format

Definitions are YAML mappings keyed by scene id. The
[loader and dataclasses](../server/content/cutscenes.py) are the exact field,
default, coercion, and limit reference. Start with the real
[tutorial definitions](../worlds/tutorial/cutscenes.yaml) or
[core definitions](../data/core/cutscenes.yaml), not a separate copied example.

The main authoring decisions are:

| Fields | Purpose |
| --- | --- |
| `title`, `script`, `frame` | Player-facing name, entry module, default frame |
| `duration`, `skip` | Safety cap and whether a user may interrupt |
| `audience`, `room_bound` | Delivery and travel behaviour |
| `hidden`, `aliases`, `max_queue` | Catalog visibility, launch names, pending-entry budget |
| `feature`, `power`, `rooms`, `energy_cost` | Per-definition launch restrictions and cost |
| `params`, `text` | Scene-specific customization and optional caption cues |

`title` is required. `script` defaults to `<id>.js`; `frame` defaults to
`plain`. `duration` is milliseconds, non-negative; zero means no cap and the
scene must end itself. `audience` is `private`, `room`, or `any`; `any` defaults
to private but permits a room request. `room_bound` and `skip` default true.

`hidden` omits a scene from the launch catalog without preventing id-based
launches (used for journal/system scenes). `feature:` gates only that
definition; cutscenes as a subsystem have no feature flag.

`params` is an open scene-specific channel, limited to 16 keys and scalar
values (strings up to 200 characters, numbers, booleans), except that
`frame_options` may be a mapping of bounded scalar options. The text cues use
`at`, `say`, `speaker`, and optional CSS `style`; at least `say` or `speaker`
must be non-empty. Current parsing defaults `at` to zero and accepts
non-negative numeric offsets, converting to integer milliseconds.
The original cue contract required an explicit integer `at`; that stricter
authoring-validation requirement remains unresolved rather than implemented.

Cues are a convenience, not mandatory rendering: a scene can ignore `text`
and build its own text DOM. Do not put indispensable gameplay information
only in a cue, since reduced motion suppresses the entire scene.

### 3.2 Directory layout and hosting

Each scene has a directory named after its id, containing its entry module
and sibling assets. All are served under `/cutscenes/<id>/<file>` (with the
configured deployment base path when applicable).

| Source | Definition location | Script directory |
| --- | --- | --- |
| Core | [data/core/cutscenes.yaml](../data/core/cutscenes.yaml) | [data/cutscenes/](../data/cutscenes/)`<id>/` |
| Enabled mod | `mods/<mod>/content/cutscenes.yaml` | `mods/<mod>/cutscenes/<id>/` |
| World | [worlds/tutorial/cutscenes.yaml](../worlds/tutorial/cutscenes.yaml) or equivalent | `worlds/<world>/cutscenes/<id>/` |

Relative sibling asset URLs work like activity assets. A scene is a module,
not a page; there is no cutscene HTML/index route.

The intended merge/search model is core → mods in load order → world, with
duplicate ids rejected rather than overridden. Alias collisions should also
fail loading. **Actual assembly and file lookup do not consistently follow
that model**: see §8. Keep ids and asset directories distinct across sources
until the conflict is reconciled; do not treat root order as an override API.

### 3.3 Validation boundaries

The [loader](../server/content/cutscenes.py) rejects malformed definitions,
invalid audiences, negative limits/costs, missing entry scripts, and invalid
params/cues. Script names must be plain `.js` filenames. Frame registration is
a client concern: an unknown frame falls back to `plain`, rather than failing
server loading.

Feature/power/room names are validated when their known sets are supplied.
The [world loader](../server/content/worlds.py) checks card `cutscene:`
references against the merged catalog. Its current check accepts ids only,
despite the intended id-or-alias contract (§8).

An authored `.cutscene` command in a prop/peep `actions:` list is not resolved
at load time. The command verb is filtered through the registered command
environment; an unknown scene id surfaces when the action runs. Validate the
binding by launching it, not merely by loading the world.

### 3.4 Cutscene emotes are cards

Use `type: emote` plus `cutscene: <id>` on a normal card with static art. The
real [Victory Dance card and pack](../worlds/tutorial/cards/) demonstrate this.
It lives in the tutorial set, not the Common-only base pack; retain that
content distinction when moving examples.

Ownership, stacking, trading, packs, and shop behavior remain card-system
concerns. Emote categories are derived from fields: `Cutscene` for a cutscene
reference, `Animation` for animation, otherwise `Expression`. See
[card loading](../server/content/cards.py), [emote costs and use](../server/services/actions.py),
and the [emote menu](../app/js/views/emote-menu.js).

A cutscene emote charges Energy (category default five; an explicit card cost
wins) and broadcasts a play event without a speech bubble or consuming the
inventory card. The ordinary “used” Action Log line remains. Playback itself
never determines whether that server-side action succeeded.

## 4. Client runtime API

### 4.1 Module shape

An entry module exports one default async function called once per playback
with `ctx`. Build inside the stage returned by `beginCutscene`, use runtime
helpers for waits/sprites/captions, and explicitly call `endCutscene()` when
finished while the manager completion gap is outstanding.

The real [Molly greeting](../worlds/tutorial/cutscenes/molly-greet/molly-greet.js)
is the basic authoring reference. Its served URL resolves the relative helper
import `../../app/js/cutscenes/stage.js` to the same stage singleton as the app,
including behind a base-path prefix. Do not import the helper under a second,
differently resolved URL: another module instance has no live session.

The manager caches namespaces by exact module URL; top-level registration is
page-global, not per playback. Intended return/rejection semantics remain in
§2.1 and §8. Do not mistake an async function finishing for a working end path
in the shipped manager.

### 4.2 `beginCutscene(frameType, options)`

Returns the live `.cutscene-stage` element, empty and sized by the frame CSS.
The scene owns its DOM and any full-bleed background. The helper configures the
manager's prepared frame; calling it twice returns the same stage. An unknown
frame name warns and falls back to `plain`.

Options combine `ctx.params.frame_options` with the explicit options argument,
with explicit options winning. Standard options are `from`, `duration`
(intro/outro CSS duration), `background`, `accent`, and `radius`. These are
frame configuration, not the definition's body duration cap.

The implementation is [beginCutscene in stage.js](../app/js/cutscenes/stage.js).
It returns the stage node, **without** the specified `dom.frame` and `dom.root`
convenience properties. Those properties remain an outstanding API requirement
(§8); authors cannot rely on them in the shipped implementation.

### 4.3 `ctx`

The exact context is assembled by [the manager](../app/js/cutscenes/manager.js).
Its author-facing data consists of:

| Data | Use |
| --- | --- |
| `id`, `title`, `frame`, `duration`, `skip` | Definition identity and playback settings |
| `audience`, `origin`, `source` | Actual delivery and triggering account (`{id, name}` when present) |
| `params` | Merged scene-specific values and server metadata |
| `text`, `assets` | Caption cues and resolved placeholder records |
| `roomId` | Room for which the event was delivered, or null |
| `signal` | Supported cancellation channel |

The intended params contract is a frozen, deep-merged object (§4.5), but only
the outer objects are frozen today. `text`, `assets`, and nested objects are
not recursively frozen. Treat them as read-only, not as mutable shared state.

`wait()` rejects with `AbortError` when the signal aborts. The runtime clears
timers it owns at close. An author must cancel timers, animation frames, event
listeners, and other work started outside runtime helpers; the runtime cannot
automatically discover arbitrary scene-owned work.

There is a contract conflict around cancellation: normal cleanup follows the
outro, while a skip must cancel the **body** before that outro. The current
single signal only aborts at close. Preserve the early-cancellation requirement
when resolving this split (§8); do not rely on the signal stopping work at the
instant a user requests skip today.

### 4.4 Frame types

A frame owns container geometry and intro/outro animations. Built-ins are
defined in [frames.js](../app/js/cutscenes/frames.js), styled in
[cutscenes.css](../app/css/cutscenes.css):

| Frame | Intended look |
| --- | --- |
| `movie` | Black 16:9 stage, entering left and leaving right |
| `vs` | Split versus screen slamming in from top/bottom |
| `letterbox` | Full-bleed stage with animated bars |
| `caption` | Transparent stage with bottom caption bar |
| `plain` | Bare stage, useful as a fallback/debug frame |

`plain` still has descriptor timing in the current implementation; “plain”
does not promise zero lifecycle delay.

Custom frames are author-extensible. Register at module top level with
`registerCutsceneFrame(name, descriptor)` before the default function runs.
A descriptor supplies `cssClass`, `introMs`, `outroMs`, and optional
`build(stage, options)` decoration. CSS uses `data-phase="intro" | "outro"`
to select keyframes; the manager controls phase timing.

[Victory Dance](../data/cutscenes/victory-dance/victory-dance.js) registers
`victory-banner`; the matching CSS is in the shared stylesheet. Custom names
are page-global and duplicate custom registration is ignored with a warning.
The runtime currently allows replacing built-in descriptors; do not treat
that exception as a general namespacing/override mechanism for content.

Frame selection and timing are split: the manager resolves the definition's
descriptor before importing the scene, while `beginCutscene` can choose another
frame later. Its waits therefore need not match a scene-selected custom frame
or an options duration. This remains a lifecycle reconciliation item (§8).

### 4.5 Parameters and captions

The intended merge order is:

1. Definition `params`.
2. Launch-time values from a command, behavior, or prop/peep target.
3. Server metadata (`origin`, `source_name`, `room_id`, `random`).

Launch values override defaults. Unknown keys intentionally pass through so a
world/mod can customize colors, text, sprites, frame options, or anything its
scene understands. The intended nested merge and immutability guarantees are
not implemented: [service `_merge_params`](../server/services/cutscenes.py)
performs a shallow replacement and the manager shallow-freezes (§8).

Command arguments are bounded scalar `key=value` pairs. The
[parser](../server/content/cutscenes.py) rejects reserved metadata names and
overlong/too-many values rather than truncating command arguments. Definition
`frame_options` is the special mapping accepted by the loader; scalar command
arguments are not an API for editing its nested options.

The intended mapping-only `frame_options` contract also applies to triggers;
the command parser currently permits a scalar under that name. Consistent
validation remains outstanding rather than an invitation to replace the map.

The server supplies a per-playback integer `random` seed so content can vary
without independently choosing `Math.random()` state on each client. Current
code uses `setdefault`, so an authored/default seed can survive; strict
server-owned metadata and consistent trigger validation remain requirements.

Captions have two paths:

- **Declarative:** use `ctx.text` and `caption(cue, options)` or
  `captions(cues)`. A single-caption handle exposes `element` and `hide()`.
- **Imperative:** build any text DOM inside the stage, including multiline or
  typewriter effects. The cue list is optional.

Cue `at` values are intended as offsets from body start. Currently `captions`
schedules offsets from when the helper is called, then clears the captions
after its final hold. The Molly example calls it after earlier animation;
authors must account for that distinction until the timing contract is aligned.

### 4.6 Placeholders and sprites

The server resolves world references at **launch**, and the client renders the
concrete records. This separates authoritative asset selection from painting;
the client never constructs an asset path by interpreting a placeholder token.

| Token | Asset source |
| --- | --- |
| `$me` | Triggering account's sticker |
| `$user:<account id>` | Another occupant's sticker |
| `$peep:<id>` | Authored NPC image |
| `$sticker:<name>` | Known preset/custom sticker name |
| `$card:<stack id or card id>` | Card art, preferring animated art when present |
| `$prop:<instance id>` | Prop model/scale for a client-rendered thumbnail |

Tokens are found inside strings in params and cues. Every emitted record has
`ref` so helpers can match it to the requesting token. `params` keeps raw
tokens; the server substitutes resolved labels in cue `say` text. Current cue
`speaker` strings contribute tokens but are not label-substituted.

Explicit `@prop:` / `@peep:` command targets inject `prop` / `peep` params with
the corresponding token and set `origin`. There is no implicit binding just
because an action appears on a prop or peep.

Missing references produce no record and do not fail a launch. Author scenes
to tolerate unavailable sprites. The current resolver checks occupancy for
`$user:` when the caller supplies occupants, room locality for `$prop:`, and
inventory ownership for stack-id card references. A direct known card id may
resolve without ownership, and a peep id resolves from the world catalog;
neither is a promise of a current-room entity.

The original launch contract required current-room peep references and owned
card references. Those scope restrictions remain outstanding where the direct
id paths above bypass them; current resolution does not supersede that intent.

See [server resolution and record shapes](../server/services/cutscenes.py),
[sprite helpers](../app/js/cutscenes/stage.js), and
[client asset rendering](../app/js/cutscenes/placeholders.js). Props are rendered
through the [shared thumbnail renderer](../app/js/editing/prop-thumbnails.js)
and returned as image elements, not a server thumbnail or a scene-owned canvas.
The server's prop `thumbnail` remains null intentionally.

Asset helpers validate URLs against the page origin (and currently allow data
URLs). Rejected/unresolvable assets fall back to neutral placeholder boxes;
give `sprite` a label when an informative missing-asset caption matters.

### 4.7 Stage helper entry points

The canonical exports/signatures are in [stage.js](../app/js/cutscenes/stage.js).
The small working set for authors is:

- `beginCutscene(...)`, `endCutscene(...)`: configure the stage and finish the
  body; the outro remains runtime-owned.
- `skipCutscene()`: request the same skip as user input, respecting `skip`.
- `wait(ms)`: a signal-aware delay.
- `caption(...)`, `captions(...)`: optional cue rendering.
- `sprite(ref, options)`, `sprites(refs)`: asynchronously prepared elements,
  ready to append and style. Prop loading may require a thumbnail render.
- `spriteUrl(ref)`: synchronous sticker/card URL, empty for props.
- `asset(ref)`: raw record or undefined.
- `registerCutsceneFrame(...)`, `frameNames()`, `currentCutscene()`: extension
  and introspection without reaching into manager internals.

Do not retain or mutate stage DOM after teardown. Use the signal for cleanup
and explicitly end the body; current limitations are collected in §8.

## 5. Launching and delivery

```
.cutscene <id|alias> [@prop:<instance> | @peep:<id>] [key=value ...] [--room] [--private]
```

Private flavor needs no command-wide power. A definition may restrict itself
with `power`, `rooms`, or `feature` and may charge Energy. `--room` is permitted
only for definitions with `room` or `any` audience; `--private` forces private
delivery. The command is quiet (`toast=False`); its Action Log line plus the
scene provide feedback. Resolution, checks, charging, and delivery are in
[commands/cutscenes.py](../server/commands/cutscenes.py).

Props and peeps use ordinary authored `actions:` entries; Molly's
[Greet binding](../worlds/tutorial/peeps/peeps.yaml) is the reference. Name both
the scene and target explicitly. Without a target the scene still launches,
but `origin` remains `command` and no target placeholder is injected.

Behaviors currently call `context.cutscene(id, audience=None, params=None)`;
the specified `room_bound=None` argument is not implemented. See
[context](../server/behaviors/context.py) and
[dispatcher](../server/behaviors/dispatcher.py). A private event targets the
acting account; room events broadcast. One bad script must never break the
room loop. Current defaults, restrictions, `room_bound` handling, and rejected
intent reporting differ from the intended contract (§8).

Play events use existing `room.event` and result `events[]` delivery. The
[service's `launch`](../server/services/cutscenes.py) is the authoritative
payload builder; scene-specific extensions belong in `params`, not arbitrary
new envelope fields. Room events reach occupants; private events carry the
account-routing identity. The server never accepts a client-selected
`script_url` as a launch parameter.

The [UI](../app/js/ui.js) intercepts play events before store dispatch. Playback
is imperative and transient, not snapshot-worthy state, and no rendering path
awaits it. Auth/transport/room state drives manager synchronization.

The [HTTP routes](../server/routes/cutscenes.py) serve static scene files and
the signed-in `/api/cutscenes` catalog. The catalog filters hidden scenes and
the remembered room, and omits script URLs. It is not a complete authorization
check; launch checks still apply. The command palette uses the server `.help`
catalog rather than this route. Unknown static assets return HTTP 404; no
special diagnostic HTML page is currently rendered.

## 6. Authoring references

Use the shipped scenes rather than maintaining copied implementations here:

| Reference | What to learn |
| --- | --- |
| [Molly greeting](../worlds/tutorial/cutscenes/molly-greet/molly-greet.js), [definition](../worlds/tutorial/cutscenes.yaml), [binding](../worlds/tutorial/peeps/peeps.yaml) | Private `movie` scene, target/default peep sprites, caption labels, paired movement and heart effects |
| [Victory Dance](../data/cutscenes/victory-dance/victory-dance.js), [definition](../data/core/cutscenes.yaml), [card/pack](../worlds/tutorial/cards/) | Room emote, custom top-level frame registration, non-room-bound playback |
| [Pack open](../data/cutscenes/pack-open/pack-open.js) | Presentation of committed rewards; gameplay state remains server-owned |
| [Task started](../data/cutscenes/task-started/task-started.js), [task completed](../data/cutscenes/task-completed/task-completed.js) | Hidden system scenes using the same runtime |

Molly costs no Energy and is room-bound flavor; `$me` can become a caption
label while remaining a sprite token in params. Victory Dance comes through
the tutorial pack and plays locally for each occupant, without synchronization.
Its custom frame styles, like Molly's coupled sprites and hearts, currently
live in the [shared stylesheet](../app/css/cutscenes.css).

When authoring, load/validate the world, launch the actual bound action, check
missing assets, skip and travel behavior, and verify reduced-motion gameplay
still communicates the result. Follow [AGENTS.md](../AGENTS.md) for content
validation and manual visual-baseline review.

## 7. Source map and verification

| Concern | Canonical implementation / coverage |
| --- | --- |
| Content fields, parsing, merge, aliases | [content/cutscenes.py](../server/content/cutscenes.py) |
| Catalog assembly and reload inputs | [bundle.py](../server/content/bundle.py), [worlds.py](../server/content/worlds.py), [mods.py](../server/mods.py) |
| Launch policy, payload, assets | [services/cutscenes.py](../server/services/cutscenes.py), [command helpers](../server/commands/cutscenes.py) |
| Card/gameplay and behavior triggers | [gameplay commands](../server/commands/gameplay.py), [actions](../server/services/actions.py), [behavior dispatcher](../server/behaviors/dispatcher.py) |
| HTTP and service wiring | [routes/cutscenes.py](../server/routes/cutscenes.py), [app.py](../server/app.py) |
| Queue, lifecycle, context, helpers | [manager.js](../app/js/cutscenes/manager.js), [stage.js](../app/js/cutscenes/stage.js) |
| Frames, sprites, focus, DOM | [frames.js](../app/js/cutscenes/frames.js), [placeholders.js](../app/js/cutscenes/placeholders.js), [inert.js](../app/js/inert.js), [CSS](../app/css/cutscenes.css), [UI](../app/js/ui.js) |
| Server/service/integration checks | [test_cutscenes.py](../tests/test_cutscenes.py) |
| Real playback smoke / motion suppression | [cutscenes.spec.js](../tests/browser/cutscenes.spec.js), [flows.spec.js](../tests/browser/flows.spec.js), [Playwright projects](../playwright.config.js) |
| Presentation/static limits | [test_ui_presentation.py](../tests/test_ui_presentation.py) |

Server tests cover content, launch, routes, audience, placeholders, and trigger
integration. They do not prove the browser manager satisfies every lifecycle
contract. The motion-enabled browser smoke checks a real command's stage and
teardown; the ordinary projects cover reduced-motion suppression. Avoid stale
test counts and claims that Python tests exercise client queue/abort behavior.

Cutscene frame visual captures (`movie`, `vs`) and deliberate emote-category
visual review remain required work. The categories now live in the emote menu,
so the old instruction to update an Emotes panel tab snapshot is obsolete.
Do not auto-approve snapshots or assume older
notes about screenshot failures describe the current tree. A peak cutscene
node counter/budget is also still absent from
[DOM perf instrumentation](../tests/browser/perf/dom-counters.js); performance
regression checks remain required when implementing runtime changes.

## 8. Outstanding contracts and deliberate deferrals

### Verified implementation gaps

These preserve intended requirements; they are not a request to adopt current
behavior as the contract. Recheck the linked implementations when resolving.

| Requirement | Current gap |
| --- | --- |
| Scene return/resolution or rejection ends the body; errors cannot stall the queue | Manager logs `played.catch(...)` but neither success nor rejection releases `bodyDone`. Explicit `endCutscene`, accepted skip/cap, or abandonment is still needed. |
| Duration is a hard safety cap even with `skip: false` | The cap calls `token.stop`, which refuses when skipping is disabled. |
| Skip aborts body work before outro | Stop releases `bodyDone` without aborting; `closeSession` aborts after the outro. Early body cancellation and post-outro DOM cleanup need a coherent contract. |
| Authored per-definition queue limits reach the client | `CutsceneService.launch` omits `max_queue`; manager therefore uses three for normal payloads. |
| Params are deep-merged and frozen, with reserved server metadata protected | Service merging and client freezing are shallow; metadata validation is not uniform across triggers, and `random` uses `setdefault`. |
| One consistent, contained lookup order; duplicate ids are errors | Core and mods load scripts against their own roots; world definitions search world then mod roots. HTTP searches core → world → mods. Bundle dictionary expansion can overwrite a core id with a mod id before strict merging. Resolve assembly/serving agreement, not just the prose order. |
| Card references resolve by id or alias | World cross-validation currently checks direct catalog ids only. |
| Room travel ends active room-bound presentation through outro | `sync()` only drops pending room-bound entries; active playback is not stopped. |
| Logout/disconnect/session replacement abandons even an active outro | `abandon()` returns once settled, so it cannot interrupt an already-running outro. |
| Reduced-motion transition fully clears active playback state | Transition closes the stage session and removes DOM, but does not release `bodyDone` or reset the active manager token/playing state. |
| Behavior launches honor definition gates/costs, private-trigger defaults, room-bound override, and rejected-intent reporting | `_apply_cutscene` calls `launch` without `check` or charging, uses definition audience defaults, and logs failures without marking `rejected`. The context API does not yet accept the specified `room_bound` override. Keep failures isolated from the room loop. |
| Stage return value exposes the specified `dom.frame` and `dom.root` references | `beginCutscene` returns only the stage without attaching these properties. |
| Placeholder scope checks apply consistently to peeps, users, and owned cards | Peep ids use the world catalog, direct card ids bypass inventory checks, and behavior launches do not supply occupants for user-reference checks. |
| Frame timing matches the selected frame/options and cue offsets are body-relative | Manager captures timing before import/`beginCutscene`; `captions` measures from helper invocation. |
| All intended board-side interactive surfaces are blocked | The shared inert sweep does not explicitly include the originally specified `#board-overlay`. |

The original behavior-intent design promised failures in `BehaviorResult.rejected`
while the implementation logs and emits nothing. This distinction matters for
diagnostics even though neither path should break the room loop. Similarly,
the runtime can clean up only work it owns; automatic cleanup of arbitrary
scene timers/animation frames was never actually provided.

### Deliberate deferrals

- **Audio:** no sound hook; scenes must not create their own `AudioContext`.
  Revisit only with a cutscene-specific sound budget.
- **Playback acknowledgement/telemetry:** requires a new design; no hidden
  reward/progression dependency may be added to playback completion.
- **Snapshot playback / late joining:** intentionally absent; missing a short
  scene is acceptable.
- **Cross-client synchronization:** unsupported and not planned.
- **Authoring UI / world-editor integration:** out of scope and not planned;
  a future editor needs an explicit design.
- **Content-shipped custom frame CSS:** deferred as a managed authoring/hosting
  feature. Current custom examples use app CSS despite sibling static assets
  being servable.
- **Queue persistence across page reload:** unsupported.
- **Visual baselines and peak scene-node perf budget:** outstanding (§7).
