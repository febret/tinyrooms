# Hacker Collective activity

The Hacker Collective is a TinyTown activity that teaches grade-school maths
inside a retro terminal heist. Players pick one of five megacorps, choose a
floor, and hack a seeded network map to reach the central server. Every node
hides one to three maths screens followed by a reflex challenge borrowed from
the Job Office. The whole floor is a thirty-minute realtime run. Grades 1 and 5
open with two floors: floor 1 is a five-node starter and floor 2 is the full
ten-node tower.

Open it from the **Hacker Collective** relay tower on the town board, or with
`.play hacker` / `.hack`.

## Grade and megacorp roster

Each grade has exactly one corporation; grades 1 and 5 are playable today.

| Grade | Megacorp | Palette | Topic |
| --- | --- | --- | --- |
| 1 | NIBBLE INDUSTRIES | P1 green `#4bff7e` | Addition and subtraction |
| 2 | AMBERLOGIC LTD | amber `#ffb347` | Addition and subtraction to 100 |
| 3 | CYANDYNE SYSTEMS | cyan `#46e6ff` | Multiplication and division facts |
| 4 | MAGNETRON GROUP | magenta `#ff5ec8` | Fractions and factors |
| 5 | TERAFORGE CORP | ice white `#d8f6ff` + red | Multi-digit multiplication |

Grades 2-4 appear on the target board with their own logo, palette, tagline,
and ten floor topics, but their cards are sealed (`ACCESS DENIED`). Each playable
corporation has floors 1 and 2 open with the same maths activities: floor 1 has
five nodes, floor 2 has ten. Floors 3-10 list their topics and stay locked.
Floor definitions carry a `nodes` count in `corps.yaml`.

## Player flow

1. **Boot** - a typed terminal sequence, then the target board.
2. **Target board** - five corporation cards. Sealed corporations glitch and
   refuse entry. An in-progress hack offers Resume or Abandon.
3. **Blueprint** - a wireframe elevation of the corporation with ten floors. The
   open floor glows and carries a blinking marker. The roommate picker and
   `JACK IN` live beside it. Bringing a roommate is always optional.
4. **Netmap** - a seeded, layered dependency graph (five or ten nodes) plus the
   central server. A node opens when all of its parents are clean; the core opens when
   all ten nodes are clean. Packet pulses travel along live edges. The thirty
   minute countdown is stored on the server, so a reconnect keeps the same
   deadline.
5. **Node intrusion** - maths screens first, then the reflex challenge. A failed
   challenge keeps the node, keeps the decrypted screens, and allows a retry
   with a new reflex seed.
6. **Central server** - three maths screens and a core challenge. Clearing it
   pays the floor rewards and ends the run.

Every node screen has a **← MAP** button (and Escape) that leaves the node at
any time. Leaving resets that node's maths screens, tips, and challenge, so
re-entering starts the node clean. The hack itself keeps running.

The list of nodes beside the map is the accessible control surface; the canvas
nodes are also clickable.

## Maths screens

Screens arrive seeded from the server. Answers are included in the payload so
the client can turn each line green instantly; the server re-checks the final
submission and owns pass/fail.

| Grade | Type | Task |
| --- | --- | --- |
| 1 | `type-in` (Decrypt Terminal) | Four one-digit additions and subtractions; type each result; each line locks green when right. |
| 1 | `match` (Packet Match) | Three two-digit +/- one-digit operations matched to a result list with decoys. A correct pair draws a glowing circuit trace into its result. |
| 1 | `fill-gap` (Patch the Gap) | Five fact-family lines with one missing number (`□ + 4 = 11`). |
| 1 | `spot-glitch` (Spot the Glitch) | Eight equations, exactly three corrupted; flag the wrong ones, then run the diagnostic. |
| 5 | `quick-pick` (Quick Pick) | Six one-digit products from three choices each, on a fifteen-second clock. A wrong pick locks that card's choices for one second. A timeout asks the server for a fresh set. |
| 5 | `long-mult` (Long Multiplication) | One four-digit by two-digit problem as a digit grid: both partial products and the total. Every digit is entered separately and turns green when right. |
| 5 | `long-mult-small` (Short Multiplication) | Two two-digit by two-digit problems, using the same digit-grid working and feedback. |
| 5 | `area-model` (Area Model Breaker) | Split a two-digit by two-digit product into four partial products, then add them. |
| 5 | `estimate-lock` (Estimate Lock) | Pick the closest rounded estimate from three plausible magnitudes. |

A node asks for `1 / 1 / 2 / 2 / 3` screens by graph depth; the core always asks
for three. A node picks distinct screen types from its grade pool.

## Reflex challenges and the phosphor skin

The six Job Office minigames are reused unchanged. The hacker client imports
them from `../jobs/minigames/` and supplies:

- `tokenPainter(kind, palette)` (`tokens.js`) as the game `sprite`. It draws a
  vector glyph for the node kind (firewall shield, data cylinder, envelope,
  gear, CRT, server) instead of using a baked image.
- `createHackSkin(palette)` (`hack-skin.js`), which re-costumes the target zones,
  pips, frame, and arena in the corporation's phosphor colour. Miss colour stays
  coral, and the "tap here" colour is always the corporation colour.
- `drawCrtOverlay` after the frame: scanlines, vignette, a moving scan band, and
  occasional flicker (suppressed by reduced motion).

Three small optional hooks make this possible without forking the games:
`runMinigame` accepts `skin` and `overlay`, and `drawSprite` accepts any object
with a `paint(ctx, size)` method. Job Office behaviour and tests are unchanged.

## Roommates

One roommate can join; they never change the maths. They change:

- **Reflex difficulty.** Each node kind maps to an approach (`firewall`→grit,
  `database`→nouse, `mail`→charm, `maintenance`→care, `legacy`→chaos). The
  engine reuses the Job Office `lead_modifier`: traits, energy, mutual vibes,
  and the player's own energy shift a hidden 1-10 difficulty that feeds
  `game_params`. The UI only shows qualitative fit labels.
- **Commentary and tips.** Authored lines in `content/hacker/banter.yaml` are
  filtered by the roommate's traits and energy mood (rested/tired/drained) and
  shown in a slim bar under the maths screen. While a maths screen is open the
  roommate also offers a tip every eight seconds: a strategy line or a safe
  arithmetic fact (`Useful fact: 7 × 8 = 56.`) chosen so it never equals an
  on-screen answer, prompt, or option. Without a roommate the bar is hidden.
- **Fatigue and vibes.** Clearing a node costs the roommate
  `FATIGUE_PER_NODE` (3) real energy; clearing the core pays `VIBE_PER_FLOOR`
  (12) vibe toward the player.
- **Availability.** The Job Office vibe gate applies: a roommate below
  `VIBE_GATE` (-50) refuses to join.

## Economy

| Event | Reward |
| --- | --- |
| Each clean node | 2–8 Bops, scaled by that node's reflex score |
| Central server | 15–40 Bops, 3 Kudos, 2 random props the player does not own |

Reflex challenges never fail: every finished run clears the node. The score
only sets the payout, from the floor rate at 0 hits to the top rate at a perfect
run. Impossible, too-fast, or over-ten-minute results still clear the node but
pay the floor rate. The netmap shows each node's 2–8 Bops range, the core's
15–40 Bops plus Kudos and props, and the running total of Bops earned. A cleared
node changes to its actual paid amount.

Starting a hack costs no energy. Rewards are once per floor per day-night
cycle: each node payout uses a ledger key
`tinytown-hacker:<account>:<cycle>:<corp>:<floor>:<node>`, and the core adds
`...:central`. A replay in the same cycle still clears nodes and reaches the
core, but reports `paid: false` and pays nothing. Node payouts are granted
immediately, so an expiry or abandon keeps the nodes already cleaned.

The central prop reward picks from locked decorative propset props the account
does not own, seeded by account, cycle, corporation, and floor. If the player
already owns everything, the two props simply collapse to none.

## Server modules

| File | Role |
| --- | --- |
| `hacker_library.py` | Strict YAML loader for corporations, floors, palettes, art files, and banter. |
| `hacker_problems.py` | Seeded generators and verifiers for the eight maths screens. Pure. |
| `hacker_map.py` | Seeded 5-12 node DAG, layer sizing, layout, and dependency helpers. Pure. |
| `hacker_engine.py` | Difficulty, challenge tuning, rewards, deadline constants, banter filtering. Pure. |
| `hacker_runs.py` | SQLite table, run lifecycle, screen/challenge state, ledger payouts, fatigue and vibes. |
| `hacker_activity.py` | Thin `.hack` command adapter; payload-only outcomes. |
| `service.py` | Lazy `hacker` property, `prepare()` table creation and content validation. |

Run state is JSON in `world.tinytown_hacker_runs`, one active row per account
(partial unique index). The deadline is an epoch stored on the row; `_clock` is
injectable for tests. Expired runs are closed lazily by the next board, resume,
or command.

Command surface:

```text
.hack [board|start <corp> [@peep:<id>]|enter <node>|leave|answer <screen> <ms> <key=value,...>|challenge|resolve <node> <id> <score> <ms>|resume|quit]
```

`resolve` applies the same anti-cheat as the Job Office: scores above
`max_score` or negative are rejected, results under 15% of `expected_ms` score
zero, and runs longer than ten minutes score zero. The server owns the
fifteen-second Quick Pick limit and the thirty-minute floor deadline.

## Client modules

| File | Role |
| --- | --- |
| `index.html` | Screen skeleton and stable ids. |
| `hacker.js` | Controller: boot, board, blueprint, map, node screens, tips, exit/reset, challenge, result. |
| `hacker-model.js` | Pure helpers (clock formatting, palette variables, answer pairs, local checks, labels). |
| `edu.js` | Eight maths renderers with instant local feedback. |
| `blueprint.js` | Wireframe corporation elevation and lit floor. |
| `netmap.js` | Network graph, packet pulses, node glyphs, hit-testing. |
| `fx.js` | Vector particles, CRT glitch streaks, typewriter and scramble text. |
| `audio.js` | WebAudio 8-bit bleeps (no new sound files or `shared.js` changes). |
| `hack-skin.js`, `tokens.js` | Phosphor skin and vector tokens for the reused minigames. |

The layout is validated at 1280x800, 1024x640, 820x400, 420x880, and
768x1024. On a portrait phone every screen fits one viewport without page
scrolling: the target board uses two compact columns, the blueprint and map
shrink, the node list becomes a two-column grid, and the maths stage uses
compact type and spacing. Reduced motion removes flicker, scan pulses,
particles, and glitch animation.

## Assets

`tools/build_hacker_assets.py` owns the list and the fallbacks:

```bash
python tools/build_hacker_assets.py --bake --placeholders --glb-placeholder --convert --check
python tools/bake_assets.py worlds/tinytown/hacker/bake.json --progress --force
python tools/build_hacker_assets.py --convert --check
```

- `--bake` writes `worlds/tinytown/hacker/bake.json`: five logos, five
  backgrounds, five minigame arenas, a viewport preview image for the prop,
  and the entry prop GLB task.
- `--placeholders` draws phosphor vector emblems and subtle terminal backdrops
  procedurally, so the strict loader passes before a real bake. `--glb-placeholder`
  copies `office-building.glb` as a stand-in until the real bake replaces it.
- `--convert` turns PNG output into WebP (logos keep alpha) and deletes the PNGs.
- `--check` reports missing art and bake-task counts.

The activity reads art from `/activities/hacker/art/<file>.webp`. Corporation
logos are baked images; their runtime vector counterparts (map glyphs, tokens,
blueprint) stay code-drawn so every screen animation remains sharp and
monochrome.

## Tests

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_tinytown_hacker
node --test tests/client/hacker.test.js
npx playwright test hacker.spec.js --project=desktop --retries=0
python -m ruff check mods/tinytown/hacker_*.py tools/build_hacker_assets.py
```

Python covers the loader, every screen generator, map invariants, difficulty
monotonicity, anti-cheat, the entry prop, sealed grades, node payouts and replay
suppression, core rewards and props, roommate fatigue, the vibe gate, deadline
expiry, and challenge retries. Node covers pure model helpers, vector tokens,
the phosphor skin against a recording canvas, and all six games drawing with the
new sprite and skin. The browser smoke covers boot, board, blueprint, map, a
node screen, a full solve plus reflex challenge, and abandon.

## Adding a grade or a screen type

1. Add the corporation to `content/hacker/corps.yaml` with `available: true` and
   a `nodes` count on floors 1 and 2, and add its grade to `SUPPORTED_GRADES` in
   `hacker_library.py`.
2. Add maths generators to `hacker_problems.py`, register them in `BUILDERS`
   and `GRADE_SCREENS`, and give each one a renderer in `edu.js`.
3. Add new node kinds to `hacker_map.py` (code, approach, glyph) and draw their
   token in `tokens.js` / glyph in `netmap.js`.
4. Re-run `tools/build_hacker_assets.py --bake --placeholders --convert --check`
   and bake the new logo, background, and arena.
