# Performance

`npm run test:perf` runs the performance suite. It is deliberately **not** part
of `npm test` or `python -m unittest discover`: the suite is slower than the
functional tests, its browser tier needs a software rasteriser, and its headline
metrics are wall-clock, so it is run deliberately rather than on every save.

```powershell
npm run test:perf                          # all three tiers, compared to the baseline
python tools/run_perf.py --tiers server    # just the in-process service benchmarks
python tools/run_perf.py --tiers client    # just the reducer benchmarks under node
```

Exit code is non-zero if any tier fails *or* any metric regressed.

## How a regression is decided

Two mechanisms, because they fail in different ways.

**Absolute ceilings, asserted inline.** Deterministic counts — SQL statements
issued, objects allocated, files walked, tasks created — are asserted inside the
test that produces them. A breach fails with a message naming the responsible
test, so the cause is obvious without reading the report.

**Relative baselines, compared afterwards.** Every tier writes its metrics to the
JSON file named by `TR_PERF_OUT`; `tools/perf_report.py` merges them, compares
against `tests/perf/baselines/perf-baselines.json` and prints a table. A metric
is a regression when it exceeds `baseline * 1.2`, plus an absolute noise floor per
unit.

Re-record after an intentional change:

```powershell
TR_UPDATE_PERF_BASELINES=1 npm run test:perf     # merges; partial tiers keep the rest
python tools/run_perf.py --update --replace-baseline   # full overwrite
```

## Tiers

| Tier | What it measures | Harness |
| --- | --- | --- |
| `server` | snapshots, broadcasts, ticks, per-message overhead, leaks | `unittest`, in-process, synthetic worlds |
| `client` | state reducer scaling and allocation | `node --test` on the real ES modules |
| `browser` | GPU resource counts, drawn frames, DOM writes and forced reflows | Playwright + `playwright.perf.config.js` |

### server

`tests/perf/perf_snapshot.py` is the important one. `RoomService.build_snapshot`
runs on connect, on every `snapshot.request`, on every `.go` and on every
`.reset_room`, and it assembles data for *every* occupant while being invoked
separately for *each* occupant. That combination is what made a busy room
quadratic.

The benchmarks count SQL statements through SQLite's own trace hook
(`perfkit.sql_counter`), so they need no changes to the repositories under test
and see statements issued inside transactions. They are therefore exact, fast,
and immune to machine load — which is why the ceilings are tight.

`tests/perf/synthetic.py` generates scaled copies of the tutorial world: N rooms,
M props, K peeps, cards and auras. **Note** the world tree is hardlinked to
avoid copying megabytes of artwork, so the generator unlinks a file before
rewriting it; `perf_synthetic_world.py` guards that, because writing through a
hardlink silently corrupts `worlds/tutorial`.

### client

`tests/client/*.test.js` already imports the real `app/js/` modules, so the
reducer benchmarks do the same under `node --test` with no browser. They assert
*identity* invariants as well as timings: a chat message must not replace the
prop, occupant or room-card arrays, and re-normalising an unchanged chat log must
not mint new identities. Those are exact and cannot flake.

### browser

The browser tier asserts on **structure, not frame timing**. Wall-clock
assertions against a software rasteriser are the least reliable signal in the
suite, so instead it budgets what the board submits to the GPU
(`renderer.info`), how many frames the loop produces, and how much DOM work a
single state change causes.

`tests/browser/perf/dom-counters.js` counts DOM writes and layout-forcing reads,
attributing an access only when an `/app/js/` frame appears in its stack.
Without that filter the count is dominated by Chromium's own `scrollTop` reads
during scroll anchoring and by Playwright's actionability checks — the first
version of this benchmark reported 1586 forced layouts for one chat message, of
which 1300 were the browser's.

## Measured results

Recorded on the tutorial world scaled to a 93-prop room and a 40-occupant room.

| Metric | Before | After |
| --- | --- | --- |
| SQL statements, 40-occupant snapshot | 203 | 8 |
| SQL statements, 64-prop snapshot | 74 | 3 |
| SQL statements, 32-peep snapshot | 42 | 3 |
| Snapshot wall clock, 30 occupants | 4.6 ms | ~3 ms |
| JSON encodes per broadcast to 40 clients | 40 | 1 |
| Asyncio tasks ticking a 40-room world | 40 | 1 |
| SQL statements, 5 idle ticks in a busy room | per occupant | 0 |
| Sticker directory walks per command | 1 | 0 |
| `json.dumps` for discarded log records | 1 per record | 0 |
| `crypto.randomUUID` per snapshot re-normalise | 50 | 0 |
| Resident textures, 93 copies of one prop | 205 | ~101 |
| Draw calls per frame, 93 props | ~2x (shadow pass) | 253 |
| Frames drawn on a hidden page | unbounded | 0 |
| Forced layouts per chat message | 1590 | 11 |
| `innerHTML` writes per chat message | whole shell | 1 |
| `inert` writes per chat message | 5+ (observer loop) | 0 |

## Known follow-up: per-instance prop geometry

Resident **geometries** still track the prop count, because GLTFLoader parses
each instance of an asset independently. Caching the parsed model and handing
each instance a clone of the node tree (`Object3D.clone(true)` shares geometry
and material references, so it costs node hierarchies rather than GPU buffers)
was implemented and measured, and it halves both texture and geometry residency
— but it broke room-editor picking in a way that survived extensive bisection
and was not safely resolvable, so it was reverted rather than shipped
unverified.

What is known about the failure, for whoever picks it up:

* It is not the clone, the shared box geometry, the debounced `fit`, the render
  loop idling, or the disposal changes — each was removed individually and the
  room-editor suite still failed.
* It is not a stale world matrix. A raycast hits a different screen position
  even though `setRayFromEvent`, the camera, the canvas rect, the NDC
  coordinates, the ray origin and direction, every prop position and every prop
  bounding box are byte-identical between the working and failing builds.
* The symptom is that a second press on a selected prop is claimed by the
  rotate/scale gizmo instead of the prop, because the gizmo's world matrix is
  not refreshed on a frame where the loop skipped rendering. `setRayFromEvent`
  now refreshes the camera, room graph and gizmo explicitly, which is correct
  regardless, but the underlying difference survived that fix.

The texture half of the problem is already solved independently:
`shareModelTextures` in `app/js/board-resources.js` dedupes prop textures per
asset without touching the model lifecycle, which is where the 205 → 101 came
from.

## Where the invariants live

Every ceiling is a comment on the code it protects, not a number in a config
file. When a benchmark fails, the failure message says which behaviour it is
holding in place.
