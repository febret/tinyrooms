# Tinyrooms — Agent Guide

## Project Overview

Tinyrooms is a multiplayer miniature-world game with an HTTPS FastAPI backend,
vanilla JavaScript + Three.js frontend, SQLite state, and YAML world definitions.
Start with [architecture](doc/architecture.md) for components, protocol, and game
flows; [README](README.md) owns setup, configuration, launch, and test commands.
[Mission Control](doc/mission-control.md) owns fleet/player-entry operations and
deployment contracts. [Dynamic peeps](doc/dynamic-peeps.md) describes future work.

## Code Conventions

- **Python**: Type-hint public functions; begin every Python file with
  `from __future__ import annotations`. Group imports as standard library,
  third-party, then local `server.*`, separated by blank lines. Avoid inline
  comments unless needed to explain tricky logic.
- Keep first-party source files **below 1200 lines**; split growing files.
  [The static check](tests/test_ui_presentation.py) covers Python, JS, CSS, and
  HTML under its listed roots. Do not add fragile CSS assertions to static tests.
- **JavaScript**: Use vanilla ES modules; app code has no build step. Preserve
  the modern browser floor (ES2020 + import maps: Chrome/Edge 89+, Samsung
  Internet 15+, Firefox 108+, Safari 16.4+). Keep
  [boot-guard.js](app/js/boot-guard.js) ES5-only: it must show diagnostics on
  unsupported engines before the module entry can run.
- **YAML**: Validate edits under `worlds/` and `data/` against the
  [content loaders](server/content/), especially [worlds](server/content/worlds.py)
  and [cards](server/content/cards.py).
- Use descriptive class, module, and function names; avoid abbreviations beyond
  established domain terms such as `peep` and `prop`.

## Testing

Use an activated virtual environment and the [verification commands](README.md#verification).
Run Python unittests, `npm test` (Node client tests + browser smoke), visual checks
when rendering changes, and [performance budgets](doc/performance.md) as appropriate.
Performance tests run separately from `npm test` and unittest discovery; deliberately
re-record baselines only for an intentional change.

### Writing New Tests

1. **Server/business logic**: Add `tests/test_*.py` using `unittest.TestCase`,
   without an external framework. Service tests should subclass
   [ServiceTestCase](tests/common.py) for isolated profile/world databases.
2. **Client logic**: Test the actual `app/js/` modules with Node's test runner
   under [tests/client/](tests/client/) (`*.test.js`); use `npm run test:client`.
3. **Browser functional**: Keep [flows](tests/browser/flows.spec.js) and
   [cutscenes](tests/browser/cutscenes.spec.js) a minimal smoke set: boot,
   WebSocket round-trip, core views, and an end-to-end gameplay flow. Do **not**
   add broader gameplay/business-logic flows here; use server or client tests.
   Use semantic selectors/stable IDs and each test's fresh HTTPS server from
   [fixtures.js](tests/browser/fixtures.js), never a live/shared server.
4. **Rendered states**: Add snapshots in
   [screenshots.spec.js](tests/browser/screenshots.spec.js). Harness geometry,
   determinism, and diff settings live in [playwright.config.js](playwright.config.js).

### Visual baselines (manual review required)

Never auto-approve screenshots or alter baselines to mask content bugs. Follow
the [baseline commands](README.md#playwright-tests-and-reference-screenshots),
explicitly opting in only after manual design review. Review generated
`tests/browser/baselines` PNGs against [design](doc/design.md) and
[image references](doc/images/), obtain approval before committing, then rerun
**without** the update flag.

## Design and Safety Constraints

- Keep the server authoritative: world state is in server SQLite; the client
  renders and dispatches input. A single process owns a world; event-loop order
  orders room broadcasts, and `request_id` matches command results.
- Keep invitation-gated registration; changing its passphrase does not change
  existing accounts. Never enable dev features by default in production.
- Keep cutscenes always live, rather than feature-flagging half the subsystem;
  the client's reduced-motion preference suppresses playback.
- Dynamic peeps propose importing agent-generated Python **in-process**, with a
  separate generation worker, immutable authored floor, validated overlays, and
  a dev warning. Never enable in production or widen the artifact import
  allowlist without rereading [the hardening gate](doc/dynamic-peeps.md) §9.
- A separate production launch path remains future work: use a different
  certificate and disable self-signed generation/hot reload there.
- Preserve [MC entry and upgrade contracts](doc/mission-control.md#21-player-entry-and-destination-resolution):
  direct same-host HTTPS worlds, shared profile DB, exact saved instance, durable
  identities/default/resume, and explicit migration of legacy launch settings.

## Modifying World Content

Validate YAML through loaders, run targeted browser smoke against the changed
world (`npm run test:browser -- -g "<test name>"`), and validate it in the game
client manually. Regenerate visuals only for intentional changes matching design.

## Before You Commit / PR

- Run Python unittests + `npm test`, relevant visuals, and performance budgets.
- Keep static checks clear, review/approve new visual baselines, and manually
  validate changed world YAML.
- Never add secrets or keys; keep local self-signed material under ignored `.local/`.
