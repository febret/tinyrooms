---
name: tinytown-activity
description: Build a TinyTown activity like the Job Office - a prop on the town diorama opens an embedded activity that drives roommates, reflex minigames, baked art, and server-authoritative rewards. Use when asked to add a new playable TinyTown activity, reuse the jobs minigames or roommate mechanics, or bake art and sound for one.
---

# TinyTown activity skill

This is the playbook distilled from building the **Job Office**
(`mods/tinytown/activities/jobs/`, `job_*.py`). Use it to add a similar activity
(a fishing dock, a tailor's shop, a school, a stage) without re-deriving the
architecture. Read [architecture](architecture.md) for the platform and
[performance](performance.md) before large visual work. The Job Office is the
reference implementation; when this doc and the code disagree, the code wins.

## Ground rules

- **No base-file edits.** Everything lives in `mods/tinytown/`,
  `worlds/tinytown/`, `tools/`, `tests/`, and `doc/`. The Job Office needed zero
  changes to `client/app/js/cards/cards.js` once the entry point became an
  ordinary prop (see [Linking the world](#1-link-the-activity-to-the-world-through-a-prop)).
  The single exception today is `client/activities/shared.js`: its `SOUND_FILES`
  table is the only way to name activity sounds, so a new activity that wants
  custom stingers must either reuse existing kinds (`tap`, `coin`, `error`,
  `open`, `close`, `notify`, ...) or ask for a hook in that file.
- **The server is authoritative.** The client renders and reports input; the
  server owns offers, difficulty, pass/fail, energy, Bops, vibes, and fatigue.
- **Keep files under 1200 lines** (Python, JS, CSS, HTML). Split early:
  `jobs.css` became `jobs.css` + `jobs-play.css`.
- **Python:** `from __future__ import annotations`, type-hinted public functions,
  stdlib / third-party / `mods.*` / `server.*` import groups.
- **JS:** vanilla ES modules, no build step, ES2020 floor. No CSS container
  queries (Firefox 108 lacks them); use media queries plus a small JS measurement.
- **Keep mechanics opaque.** Show qualitative labels ("In their element", "Out of
  their depth", "drained"), never formulas or numbers for hidden odds.

## Anatomy of an activity

```text
mods/tinytown/
  content/activities.yaml          # registers the activity kind and its rooms
  content/<feature>/*.yaml         # authored content, validated by a strict loader
  <feature>_library.py             # strict YAML loader -> frozen dataclasses
  <feature>_engine.py              # pure rules: difficulty, params, resolution (no I/O)
  <feature>_runs.py                # persistence + lifecycle + payloads (owns SQLite rows)
  <feature>_activity.py            # the `.<feature>` command handler
  mod.py                           # register_command(...) wiring
  service.py                       # lazy `.<feature>` property + prepare()
  activities/<feature>/            # the iframe app, served at /activities/<feature>/
    index.html  <feature>.js  <feature>-model.js  <feature>.css  <feature>-play.css
    minigames/ scene/              # reusable client modules (see below)
    art/ sprites/ arenas/          # baked WebP assets
worlds/tinytown/
  props/props.yaml  props/*.glb    # the entry prop definition and model
  rooms/rooms.yaml                 # places the prop in a room (usually `town`)
  sounds/*.wav                     # stingers, served at /assets/sounds/<file>
tools/build_<feature>_assets.py    # bake lists, placeholders, WebP conversion, checks
tests/test_tinytown_<feature>.py   tests/client/*.test.js   tests/browser/<feature>.spec.js
doc/<feature>-activity.md
```

Module split rationale (it paid for itself): `engine` is pure and exhaustively
unit-testable, `runs` is the only code touching SQLite, `activity` is a thin
command adapter, and the client mirrors it with a pure `model` (state) and a thin
DOM controller.

## 1. Link the activity to the world through a prop

An activity needs a door in the world. The Job Office is a **prop** on the `town`
diorama. Do not invent a special "house" entry or add `if (selected.office)`
branches to base client files: a prop already provides selection, a card, the
board selection ring, and quick-action buttons.

### 1a. Define the prop (`worlds/tinytown/props/props.yaml`)

```yaml
tinytown-job-office:
  label: Office of Odd Jobs
  description: A civic building with too many forms ...
  model: office-building.glb        # lives next to props.yaml
  decorative: true
  default_actions:                  # [label, command, default?]
  - - Clock in at the Job Office
    - .play jobs
    - true
  scale: 0.625
  sprite_footprint:
  - 12
  - 12
  tags:
  - civic
  - office
  - jobs
```

- `default_actions` is the entry command. Use `.play <activity-kind>` (the kind
  registered in `activities.yaml`) so the existing activity launcher handles the
  room restriction, replacement of an already-open activity, and the iframe.
- The prop file declares `CONFIG: scale_adjust: 1.6` at the top, so the loaded
  definition scale is `scale * 1.6`. The server sends `instance.scale *
  definition.scale`; **instance scale did not stack in practice** (a room
  instance `scale: 2` still delivered the definition scale), so tune the
  **definition** scale.
- These YAML files use CRLF line endings. Edit them with a tool that preserves
  them (read/write bytes), or the diff becomes a whole-file rewrite.

### 1b. Place it in a room (`worlds/tinytown/rooms/rooms.yaml`)

```yaml
town:
  props:
    jobs-office:
      prop: tinytown-job-office
      pos: [23.44, 73.88, 2.06]     # [x%, depth%, elevation units]
      rot: [0, -4.6, 0]             # degrees, [x, y, z]; the room key is `rot`
      scale: 1
```

The room loader reads `rot` (the snapshot reports it as `rotation`). The
diorama's props render with the generic board prop pipeline, so a GLB sits in the
procedural town without any mod board code.

### 1c. Calibrate placement and size on a diorama

The `town` board is a procedural height field (`mods/tinytown/boards/terrain.js`),
so a prop must be grounded by hand:

```text
x% = worldX / 0.1205 + 50          depth% = worldZ / 0.1005 + 50     # BOARD_*_PER_PERCENT
elevation = (maxTerrainHeightAround(worldX, worldZ, radius) + 0.01) / 0.1
group scale ≈ desiredWidth / modelWidth   # e.g. 1.0 / 2.0 -> 0.5, then divide by scale_adjust
```

1. Compute `terrainHeightAt` over a ring around the lot in Node
   (`import { terrainHeightAt } from "mods/tinytown/boards/terrain.js"`); pick a
   spot where the whole ring is above `WATER_LEVEL` (0.035) so the building does
   not overhang the shore.
2. Read the GLB extents (accessor `min`/`max` in the glTF JSON chunk) to size it.
3. Screenshot the town, then **click the prop** and confirm the card shows the
   label and the entry button. A throwaway Playwright spec that logs in, waits
   ~6 s, screenshots a clip, and clicks the prop's screen position is enough.
   Delete it afterward.

### 1d. Make the prop art

Bake a preview image and then the GLB from it with `tool: asset` tasks (see
[Baking assets](#5-baking-assets)). Keep the preview in
`worlds/tinytown/rooms/preview-<name>.png`; it feeds the GLB bake and is useful
documentation. The prop task for the office:

```json
{ "label": "tinytown-office-building", "tool": "asset",
  "prompt": "cozy storybook miniature civic office building diorama ... isolated game asset, no text",
  "output": "worlds/tinytown/props/office-building.glb",
  "args": { "image": "worlds/tinytown/rooms/preview-office-building.png", "seed": 97150, "faces": 7500 },
  "simplify": false }
```

### 1e. Register the activity

`mods/tinytown/content/activities.yaml`:

```yaml
jobs:
  title: TinyTown Job Office
  aliases: [work, shift, office]
  rooms: [town]                # restrict where `.play jobs` works
```

The `kind` key (`jobs`) is the join between the prop's `.play jobs` action, the
command module, and `/activities/jobs/index.html`.

## 2. Server structure

### 2a. Command (`<feature>_activity.py` + `mod.py`)

```python
api.register_command(
    "jobs", "Open the Job Office or manage a shift.", tinytown_jobs_command,
    usage=".jobs [board|start ...|challenge ...|resolve ...|resume|quit]",
    help="...", toast=False, log=False,
)
```

Pattern used by the handler:

- No args (or `open`) -> `start_activity(context, ResolvedActivity(definition=...),
  room_id=require_room_id(context), replace_existing=True, extra_config={...})`.
- Every other subcommand first calls `_require_open(context)` (the player must
  have the activity open), then returns
  `CommandOutcome(message="", toast=False, log=False, payload={...})`. The iframe
  reads `response.payload`; nothing goes into the chat log.
- Convert service `ValueError`s to `CommandError(str(exc))` so the iframe gets a
  clean `ok: false` message.
- Include `serialize_user(...)` as `payload["user"]` when energy/Bops changed so
  the UI can refresh the wallet.

### 2b. Service wiring (`service.py`)

```python
@property
def jobs(self):
    from mods.tinytown.job_runs import JobRuns
    if getattr(self, "_job_runs", None) is None:
        self._job_runs = JobRuns(self)
    return self._job_runs
# in prepare():  if self.available: self.jobs.prepare()   # creates tables, loads + validates content
```

`available` is `world.id == "tinytown"`. Loading content in `prepare()` means a
bad YAML or a missing asset fails at startup, not mid-game.

### 2c. Strict content loader

Validate everything (ids, enum values, counts, text lengths, that **every
referenced asset file exists**). The loader is the contract that keeps authors
honest; make it raise `ContentError` with the file/path in the message. Add
`required` fields rather than defaults when a missing value would silently
degrade the game (the jobs loader requires `game`, `sprite`, art, sprites, and
arenas for every step).

### 2d. Pure engine

Keep rules free of I/O so they can be tested in microseconds:

- `difficulty_for(...)` -> hidden 1-10 score from content tier/step, the lead's
  traits, **energy**, support energy, and mutual vibes.
- `game_params(game, difficulty, seed, fatigue)` -> tuning values per minigame
  (speed, band, tolerance, counts, `required`, `max_score`, `expected_ms`).
- `prepare_challenge(...)` / `resolve_challenge(...)` -> create and settle one
  attempt; mutate the run dict only.

### 2e. Run state and persistence

The Job Office keeps **no table of its own**. Active shifts live in a dict keyed by
account (`JobRuns._active`) and the board's "already filed" jobs live in
`_filed[(account, cycle)]`; a server restart forgets both, which is an accepted
tradeoff for a ten-minute board. Mutate the run dict in place, and keep these rules:

- Check "no active run" and "not already filed" **before** charging energy.
- Settle exactly once: `del self._active[account.id]` first, run the payout
  transaction, and restore the entry if it raises. File the result only after the
  transaction commits.
- Wrap multi-effect payouts in one `self.hub.transaction()` (Bops grant plus vibe
  deltas). Charge energy in its own transaction at start.
- Keep payouts idempotent through the persistent ledger:
  `progression.grant_in_transaction(connection, account.id, bops=..., ledger_key=
  "tinytown-job:<account>:<cycle>:<job>", kind="...")`. After a restart the board
  resets but the same key still stops a repeat Bops payout (vibe deltas have no
  such key and can repeat).
- Prune old filed entries each time the board loads so memory stays bounded.

If you later need shifts to survive restarts or want history, add a
`CREATE TABLE IF NOT EXISTS world.<table>` with a partial unique index per active
run and guard finalize with `UPDATE ... WHERE status = 'active'` plus `rowcount`.

### 2f. Board cycles synced to the day-night clock

Do not key offers to a real-world date. The sky and the board must turn over
together:

```python
from server.content.lighting import DAY_NIGHT_CYCLE_SECONDS, cycle_index, cycle_remaining, cycle_phase, phase_to_environment

day_key = f"cycle-{cycle_index(self._clock())}"          # self._clock = time.time (injectable)
rng = random.Random(f"tinytown-jobs:{account_id}:{day_key}")   # deterministic offers
```

Send `cycle: {index, seconds, remaining, phase, environment}` with the board; the
client keeps a live countdown and reloads the board when it hits zero (toasting
if the player was mid-selection). Pin `JobRuns._clock` in tests; a ten-minute
cycle will otherwise straddle a boundary and flake.

### 2g. Payload contract

Send what the UI needs, nothing that reveals the odds: current step title and
task text, image URLs (`art_url`, `sprite_url`, `arena_url`), a qualitative `fit`
`{label, pips}` per candidate lead, a `fatigue` (0-1) for visuals, `used` flags,
a `log` of resolved steps, and the player's display name. Resolve results carry
`passed`, `score`, `required`, `total`, narration, and the next run payload.

## 3. Reusing the roommate mechanics

Household peeps ("roommates") are `NpcRecord`s owned by an account.

| Need | API |
| --- | --- |
| List the player's roommates | `service.npcs.records_for_owner(account.id)` |
| One roommate | `service.npcs.record_for(npc_id)` |
| Stats / traits | `record.stats` (`energy`, `health`, `cleanliness`), `record.traits` (ids in `TRAITS_BY_ID`) |
| Vibe toward player / back | `service.npcs.vibes.get(npc_id, account_id)` and `get(account_id, npc_id)`; gate with `vibe > VIBE_GATE` |
| Apply vibe deltas | `vibes.adjust_many_in_transaction(connection, [(npc_id, account_id, delta), ...])` |
| Portrait art | `/assets/world/<world>/peeps/<avatar-file>`; peeps are **full-body transparent PNGs** |
| Qualitative energy text | `mods.tinytown.roommate_dialog.condition_label(value)` |
| Player energy | `runtime.stats.snapshot(account.id)`; charge with `stats.charge_in_transaction(connection, account.id, cost)` |

Mechanics worth copying:

- **Snapshot roommates at start.** Copy name, avatar, traits, energy, health,
  cleanliness, and both vibe directions into the run's JSON so a long run is not
  disturbed by live drift.
- **Traits -> approaches.** `APPROACH_PRIMARY` / `APPROACH_SUPPORT` map the five
  challenge styles (`grit`, `nouse`, `charm`, `care`, `chaos`) to trait ids; each
  step's `pool` picks the challenge, and matching traits lower difficulty. The
  authored narration choice shown is whichever best fits the lead's traits.
- **Energy matters a lot.** `energy_modifier(e)` gives rested leads up to -1.4,
  0 at 55, and a steep `6.0 * ((55-e)/55) ** 1.4` penalty below, so a drained
  peep is clearly the wrong pick. Support energy (the player's own) counts at half
  weight when a roommate leads.
- **Fatigue is persistent.** After leading a scene, subtract `FATIGUE_PER_STEP`
  from the roommate's real `energy` (the jobs code writes through
  `npcs._write(npcs._with(record, stats=...))`; wrap this in try/except so a
  write failure never breaks a shift, and prefer adding a public NPC method if
  you extend it).
- **Each roommate leads once per shift** (`used_lead_ids`). The player can always
  lead. With three roommates and four scenes the player must lead at least one,
  which makes "who goes where" the strategy. Only a *resolved* scene burns a lead.
- **Vibes pay out to every invited roommate**, led or not, at settlement.
- **Opaque UI.** A pick card shows traits, a qualitative energy label, the fit
  chip, and a "drained" marker when `fatigue >= 0.5`; the selected lead shows a
  5-pip challenge meter. No numbers.

## 4. Reusing the minigames

Six templates live in `mods/tinytown/activities/jobs/minigames/`:
`drop-catch`, `sweep-stop`, `ring-match`, `rhythm-lane`, `pop-whack`,
`hold-meter`. They are deterministic, seeded state machines on an 800x450 logical
stage; rendering is separate from rules.

### 4a. Game contract

```js
const game = createGame(id, { ...params, seed });   // minigames/index.js
game.update(dt);                 // advance time
game.press(point?) / game.release() / game.key?.(key)   // return "hit" | "miss" | null
game.draw(ctx, spriteImage, { reducedMotion, skin });
game.score        // { outcomes: ["hit"|"miss"], hits, maxScore, penalty }
game.finished
```

Server-side `game_params` must emit, per game, at least `required`, `max_score`
and `expected_ms`, plus the game's own tuning. Reuse them unchanged by choosing a
`game` per step; to add a seventh template, add a module, register it in
`minigames/index.js` (`GAMES` + hint), add it to the loader's `GAMES` tuple and to
`game_params`, and write oracle/idle tests (below).

### 4b. Running one

```js
import { runMinigame } from "./minigames/runner.js";
const handle = runMinigame({
  host, gameId, params, sprite,            // sprite: round-masked token image
  theme, arena,                            // skin (themeFor(jobId)) + baked backdrop Image
  reducedMotion,
  onResult: kind => { /* every newly scored outcome, including timeouts */ },
  onPhase: (name, detail) => { /* "countdown" | "play" | "done" */ },
});
const { score, elapsedMs } = await handle.promise;   // handle.cancel() rejects
```

Report `score` and `elapsedMs` to the server (`.<cmd> resolve <challenge_id> <score> <ms>`).
The server decides: `passed = score >= params.required`.

### 4c. Anti-cheat that does not punish players

- Reject impossible scores (`> max_score`), unknown or replayed challenge ids, and
  absurdly long runs (> 10 min). These are errors.
- A result **faster than 15% of `expected_ms` scores zero** rather than raising. An
  earlier 45% rule *rejected perfect Sweep Stop play* (measured: perfect runs end
  at ~37% of the estimate) and left the UI stuck after mashing. Measure oracle
  play (`.local` script driving each game with a perfect player) before choosing a
  threshold, and degrade to a fail, never to an error.
- The client is still trusted within those bounds; say so in the docs.

### 4d. Per-job look ("skins")

`minigames/skin.js` + generated `minigames/themes.js` re-costume the six games
without changing rules: baked **arena** backdrop under a tinted vignette; target
zones (bands, arcs, ring tolerance, hit zones, mounds, hold band) in the theme
hue with one of 10 fill patterns and one of 5 edge styles; HUD pip shape, frame
corners, marker, and heading font. `tools/build_job_themes.py` assigns a unique
pattern/edge pair per job and spreads hues by the golden ratio.

For a new activity, either reuse `themeFor(id)` with a new theme table or
generate one the same way. Keep roles fixed: the theme colour means "tap here",
coral always means a miss, and hint text says "marked", never "green".

### 4e. Low energy in the minigame

`params.fatigue` (0-1) drives `drawDrowsy`: an edge vignette from 0.3, and
periodic "eyelids" over the playfield from ~0.5. Difficulty already scales the
tuning; the overlay makes the handicap visible. Respect `reducedMotion` (static
vignette only).

## 5. Baking assets

The generator is `tools/bake_assets.py` (a wrapper over `../delphi-comfyui`).
**Never bake sound through it.**

```bash
python tools/bake_assets.py worlds/tinytown/jobs/bake.json --progress           # one list
python tools/bake_assets.py LIST.json --filter arena-plumber-step-1 --force    # re-render a subset
python tools/bake_assets.py LIST.json --dryrun
```

### 5a. Generate the lists from content

Do not hand-write hundreds of tasks. `tools/build_jobs_assets.py` is the template:

- `--bake` writes `worlds/tinytown/jobs/bake.json` (backgrounds),
  `.../sprites/bake.json`, and `.../arenas/bake.json` from the YAML (labels like
  `sprite-<job>-step-<n>`, seeded by `sha256(job, suffix)` for stable results).
- `--placeholders` writes dark gradient/circle WebPs so the strict loader passes
  while real art bakes; real bakes later overwrite them.
- `--convert` turns baked PNGs into WebP and deletes the PNGs. Sprites get a
  **round alpha mask** (4x supersampled); backgrounds/arenas are RGB WebP.
- `--check` reports `backgrounds=/ sprites=/ arenas=/ missing=` counts.

Gotchas: `bake_assets.py` skips tasks whose **PNG** output exists, so converting
(which deletes PNGs) makes a later full bake re-render them. To preview art
mid-bake, write WebPs from the PNGs *without* deleting the PNGs.

### 5b. Asset kinds and prompts

| Kind | Size | Steps | Time each | Prompt recipe |
| --- | --- | --- | --- | --- |
| Step background | 1024x576 | 28 | ~70 s | setting + scene + "cozy storybook miniature diorama ... no people, no text" |
| Minigame arena | 768x432 | 24 | ~37 s | scene + setting + "overhead flat-lay close-up, low contrast, darkened edges, calm empty center, no people" |
| Sprite token | 512x512 | 24 | ~29 s | one concrete object + "single centered object on a round cream badge, thick dark outline, flat cel shading, no text" |
| Prop GLB | - | - | longer | `tool: asset` from a preview image, `faces: 7500` |

- Keep a strong shared **negative prompt** (people, faces, hands, text, letters,
  numbers, watermark, logo) and repeat the no-people/no-text constraint in the
  prompt. Early bakes put people and signage in scenes until both were added.
- The image backend (ComfyUI) runs **one job at a time**; parallel bakes fail.
  Budget hours: 200 arenas ~2 h, 300 backgrounds ~5.5 h, 200 sprites ~1.6 h. Run
  long bakes in the background with the convert step chained after.
- **Always QA with a contact sheet** (PIL grid of every asset at ~120-190 px).
  Sprite descriptions that read as discs ("round golden coin", "paper receipt")
  came out as unreadable blobs; swap them for iconic, silhouette-rich objects
  ("golden piggy bank", "kettlebell") and re-bake only those labels with
  `--force --filter`. Write the description rules into your content brief:
  one concrete object, 3-15 words, no people/hands/faces/text.

### 5c. Sounds

Source with `../delphi-s101/delphi-s101-skill.md` (not `bake_assets.py`), then
trim, fade, normalize, and save as mono 44.1 kHz 16-bit WAV in
`worlds/tinytown/sounds/`. They are served at `/assets/sounds/<name>.wav`; name
them in the activity through `SOUND_FILES` (see ground rules).

### 5d. Authoring text at scale

Use parallel sub-agents, each owning a **disjoint set of files** (we split 50 jobs
across five agents for `game:` and `sprite:` lines) and have each verify with a
`yaml.safe_load` one-liner. Do structural edits (inserting fields in every step)
with a script that only touches matched lines.

## 6. Client structure

### 6a. Files

- `index.html` - semantic skeleton, `role="status"` live region, ids the JS needs.
- `<feature>-model.js` - **pure** helpers (labels, countdown formatting, reward
  tables) with Node tests.
- `<feature>.js` - the controller: one `state` object, `show(screen)`, render
  functions, and command calls via the bridge.
- `scene/` - `model.js` (pure), `draw.js` (canvas), `index.js` (canvas owner).
- `minigames/` - games, `runner.js`, `skin.js`, `themes.js`.

### 6b. The TinyActivity bridge (`/activities/shared.js`)

```js
await TinyActivity.command(".jobs board");          // -> { payload, ... }
TinyActivity.sound("coin"); TinyActivity.toast("msg", isError);
TinyActivity.subscribe(host => { /* host.user.shared_energy, host.config.reducedMotion */ });
TinyActivity.close("complete" | "cancel");
TinyActivity.image(url); TinyActivity.escape(text); TinyActivity.state;
```

Boot defensively: refresh the board on first `subscribe` **and** after a ~900 ms
fallback timer. Query every element once at module top, and **guard against
elements that are removed from the HTML later** - a trimmed `index.html` that no
longer has `#board-note` or `#screen-subtitle` crashed `renderBoard` with
`Cannot set properties of null` until the JS was updated to match. After any HTML
edit, diff the `querySelector("#...")` ids in the JS against the `id="..."` set
in the HTML (a five-line script does it).

### 6c. The scene beside the game

`createJobScene({ canvas, reducedMotion, seed, onPick })` renders the step
background (slow Ken Burns), the cast, a token pile, effects, and speech bubbles:

```js
scene.setStep({ artUrl, spriteUrl, accent });          // new step: reset effects
scene.setCrew([{ id, name, avatarUrl, used, you }]);   // the player's id is YOU ("you")
scene.model.setLead(id, fitLabel, fatigue);            // lead steps forward, bench shrinks
scene.model.begin({ required, total, difficulty, fatigue });
scene.model.go(); scene.model.hit(); scene.model.miss(); scene.model.finish(passed);
scene.start(); scene.stop();                           // only run the loop on the run screen
```

Design lessons: model/draw split so the model is Node-testable (layout bounds for
landscape, portrait, and tiny windows; effect cleanup; reduced motion); spring
layouts so characters glide into role changes; cap sticker upscaling (~2.4x) since
player stickers are low-res; keep reactions in text as well as motion.

### 6d. Layout that fits landscape and portrait with minimal whitespace

- The run screen is a CSS grid **stage**: two columns (scene | panel) when
  `(min-width: 701px) and (min-aspect-ratio: 6 / 5)`, otherwise stacked
  (`minmax(170px, 1fr) auto` rows). Phase (`data-phase="pick|play|result"`)
  re-weights the columns (more width to the panel while playing, to the scene on
  the result).
- Make the shell a flex column so the active screen can **fill the height**
  (`flex: 1 0 auto`); in two-column mode give the panel `overflow-y: auto`.
- **`fitPanel()`**: after every render/phase change/resize, if
  `panel.scrollHeight > panel.clientHeight` add `is-tight` (hide the timesheet),
  then `is-tighter` (hide the story blurb), then `is-compact` (shorter picker).
  Escalate-only when observing inner growth (`ResizeObserver` on the game box);
  reset only on stage resize or phase change, or the classes oscillate.
- Dedicated short-window mode (`max-height: 430px`): 2x2 picker, hidden hints, a
  **height-capped minigame canvas** (`max-width: calc((100vh - Npx) * 16 / 9)`).
- Panels that mix media should use `flex: 1 0 auto` (never shrink) so overflow is
  detectable; `flex: 1` + `min-height: 0` made content overlap instead.
- Hide chrome you do not need during play (the large heading) and keep buttons in
  the scene's top bar.
- Respect `prefers-reduced-motion` in CSS and in canvas (no shake/particles).

### 6e. Board of offers

Three cards fill the window (grid `auto-rows: minmax(0, 1fr)`, art grows); on
narrow screens they become horizontal cards. Show the cycle label ("Dusk - new
shifts in 3:41") and tick it each second with `setInterval`.

## 7. Testing

- **Python** (`tests/test_tinytown_<feature>.py`, `unittest`, no framework):
  library shape (counts, distinct games/sprites, every asset file exists, bake
  lists cover every output, themes cover every job via a regex over `themes.js`);
  engine (monotonic energy curve, drained vs rested >= 4 difficulty, params scale
  with difficulty, once-per-roommate, cancelled challenge does not burn a lead,
  fast result scores zero, tamper errors); integration over the WebSocket using
  `IntegrationTestCase` (board cycle rollover with `jobs._clock` pinned, exact
  rewards, quit cash-out, vibe gate, fatigue persisted). Assert the **entry prop**
  is in the town snapshot with the right default action.
- **Node** (`tests/client/*.test.js`, `node:test`): games driven by perfect, idle,
  and mashing players at easy/hard params; skins drawn against a **recording
  Proxy canvas** for every theme x game; scene model events and layout bounds;
  pure model helpers.
- **Browser** (`tests/browser/<feature>.spec.js`): keep it a **minimal smoke
  set** - boot, one real play-through that mashes Space until the result shows,
  and the picker rule. Use stable ids and the per-test server. The headless
  renderer runs at ~3 fps, so minigames run in slow motion: give long tests
  `test.setTimeout(150_000)` and loop `canvas.press("Space")` rather than timing.
- Throwaway visual specs (screenshots at 1280x800, 1024x640, 820x400, 420x880,
  768x1024) are great for layout QA; **delete them before finishing**.
- Pin clocks and randomness: `JobRuns._clock`, seeded `random.Random`, `mulberry32`
  in games.

Commands:

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_tinytown_<feature>
npm run test:client
npx playwright test <feature>.spec.js --project=desktop --retries=0
python -m ruff check mods/tinytown/<feature>_*.py tools/build_<feature>_assets.py
```

(`PYTHONIOENCODING=utf-8` avoids a Windows console crash on emoji vibe labels.
Three `tests/test_room_grid.py` failures predate this work; leave them.)

## 8. Build order that worked

1. **Content schema + loader + library tests** (placeholders for art).
2. **Pure engine** + unit tests (difficulty, params, resolution).
3. **Persistence + command + payloads**, then integration tests.
4. **Entry prop** + activity registration; verify the click-to-open flow.
5. **Client**: model, board, crew, run screens; browser smoke.
6. **Minigames/scene/skins**, Node tests, then visual QA at all sizes.
7. **Bake assets** (start long bakes early, in the background, while coding),
   QA contact sheets, re-bake outliers, `--convert`, `--check`.
8. **Docs** (`doc/<feature>-activity.md`) and a final full-suite run.

## 9. Pitfalls and lessons

- **Don't touch base client files for the entry point.** Using a prop removed a
  13-line `cards.js` branch and a fake house entry in one move.
- **Name and comment every tuning constant** (see the top of `job_engine.py`): what it controls, its units, and the range it was tuned in.
- **Content-driven everything**; one loader error at boot beats a broken card.
- **Heredocs with many triple quotes break the shell tool.** Write patch scripts
  to `.local/` with the write tool and run them; use `str.replace` with `assert old
  in text` so a drifted file fails loudly instead of silently not patching.
- **Escaping:** in edit tools a literal `\n` inside a Python string becomes a real
  newline; check generated JSON/Python with `cat -A` and ruff.
- **Check what the user changed between turns.** Trimmed HTML elements broke JS;
  `doc/` files can be removed. Re-read before assuming earlier state.
- **Measure before you add anti-cheat limits** (the 45% -> 15% fix above).
- **Avoid cliffs in difficulty:** clamping at 10 hides penalties on hard jobs; lower
  the base so energy/trait modifiers have headroom (`base = 2.6 + tier*0.8 + step*0.4`).
- **Do not use numbers in the UI for hidden odds**; labels and pip meters only.
- **`flex` + `min-height: 0` hides overflow.** Let content keep its natural size
  and detect overflow instead.
- **Place focus and Escape handling deliberately** (a minigame overlay once
  covered the Leave button; add an explicit "Back out" and Escape).
- **Disabled state belongs in one place** (`setBusy` owns the start button) or
  auto-selected leads leave it stuck.
- **Ruff noise:** `mods/tinytown/mod.py` and `tools/` carry pre-existing lint;
  lint only the files you add.
- **Nothing ships committed by the agent.** Leave commits to the user.

## 10. New-activity checklist

- [ ] `activities.yaml` entry (kind, aliases, rooms).
- [ ] Entry prop in `props.yaml` + placed in `rooms.yaml`; GLB baked; placement
      calibrated; click shows the card and entry button.
- [ ] `.<cmd>` registered in `mod.py`; handler uses `_require_open`; payload-only
      outcomes.
- [ ] Loader validates content and asset files; `prepare()` loads it.
- [ ] Engine is pure; settlement is exactly-once with idempotent ledger keys.
- [ ] Board/cycle tied to `DAY_NIGHT_CYCLE_SECONDS`; `_clock` injectable.
- [ ] Roommates snapshotted; vibe gate; once-per-shift rule; fatigue persisted.
- [ ] Minigames reused via `game_params` + `runMinigame`; anti-cheat degrades to a
      fail; themes/arenas/sprites present for every step.
- [ ] Layout verified at the five viewports; reduced motion honored; no numbers shown.
- [ ] Tests: Python, Node, minimal browser smoke; throwaway specs removed.
- [ ] Asset lists regenerated from content; `--check` clean; contact sheets reviewed.
- [ ] `doc/<feature>-activity.md` written; line-count limits respected.
