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
JSON file named by `TR_PERF_OUT`; the [runner](../tools/run_perf.py) merges them
and [reporter](../tools/perf_report.py) compares against the
[baseline](../tests/perf/baselines/perf-baselines.json). For lower-is-better
metrics, regression means `current > max(baseline * 1.2, baseline + noise_floor)`;
for higher-is-better, `current < min(baseline * 0.8, baseline - noise_floor)`.
Thus a change must exceed both the 20% tolerance and the unit's absolute floor,
not their sum. Floors are defined in the reporter; new/removed metrics are informational.

Re-record after an intentional change:

```powershell
python tools/run_perf.py --update           # merges; partial tiers keep the rest
python tools/perf_report.py --results "path/to/merged-results.json" --update --replace-baseline
```

Full replacement is a **reporter** option requiring an existing merged results
file, not a runner option. The runner deletes its temporary results on exit.

## Tiers

| Tier | What it measures | Harness |
| --- | --- | --- |
| `server` | snapshots, broadcasts, ticks, per-message overhead, leaks | `unittest`, in-process, synthetic worlds |
| `client` | state reducer scaling and allocation | `node --test` on the real ES modules |
| `browser` | GPU resource counts, drawn frames, DOM writes and forced reflows | Playwright + `playwright.perf.config.js` |

### server

The [snapshot benchmarks](../tests/perf/perf_snapshot.py) protect the former
busy-room quadratic path: assembling every occupant's data separately for each
recipient. [SQL counters](../tests/perf/perfkit.py) use SQLite's trace hook,
including statements inside transactions, for exact, load-independent ceilings.
The [synthetic-world generator](../tests/perf/synthetic.py) scales tutorial rooms,
props, peeps and cards. It hardlinks artwork and must unlink before
rewriting; the [guard benchmark](../tests/perf/perf_synthetic_world.py) prevents
corruption of `worlds/tutorial` through shared links.

### client

The [reducer benchmarks](../tests/perf/client/state-perf.test.js) import real
`client/app/js/` modules under Node. Alongside timings, exact identity invariants require
chat to preserve prop, occupant and room-card arrays, and unchanged chat-log
normalisation to preserve identities.

### browser

The [browser budgets](../tests/browser/perf/render.spec.js) assert on **structure,
not frame timing**: GPU submissions (`renderer.info`), frames produced, and DOM
work per state change. Software-rasteriser wall-clock timing is unreliable.

[DOM counters](../tests/browser/perf/dom-counters.js) count writes and layout-forcing reads,
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

### Room renderer follow-up

The board no longer renders a full-resolution scene/mask pair for selection
outlines. It writes the visible silhouette to the stencil buffer and draws a
screen-space hull into the default framebuffer, so selecting a prop allocates no
render targets and performs no full-screen composite. Shadow invalidation is
also separate from color invalidation, and the animation loop stops when the
room is settled.

| Metric | Before | After |
| --- | --- | --- |
| Outline render targets | scene color + depth + mask | none |
| Outline composite taps per pixel | up to 33 | 0 |
| Draw calls per frame, 101 props | 261 | 125 |
| Resident textures, same room | 121 | 104 |
| Shadow invalidations during one camera orbit | every frame | 0 |
| Animation ticks in a settled room | continuous | 0 |
| Draw calls per room card | 6 | 3 |

The browser budgets in [render.spec.js](../tests/browser/perf/render.spec.js)
now assert the idle-tick, orbit-shadow, and selection-outline guarantees
directly.

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
`shareModelTextures` in [board resources](../client/app/js/board/board-resources.js) dedupes prop textures per
asset without touching the model lifecycle, which is where the 205 → 101 came
from.

## Where the invariants live

Every ceiling is a comment on the code it protects, not a number in a config
file. When a benchmark fails, the failure message says which behaviour it is
holding in place.
