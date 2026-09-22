# Tinyrooms — Agent Guide

## Project Overview

Tinyrooms is a multiplayer miniature-world game with an HTTPS FastAPI backend, vanilla JavaScript + Three.js frontend, and YAML-based world definitions. This repo implements Milestone 2, a secure persistent vertical slice covering accounts, rooms, cards, WebSocket presence, chat, and activity windows plus the gameplay systems (stats/counters, inventory, skills, friends, shop, and the reward ledger). See [doc/architecture.md](doc/architecture.md) for the technical architecture (components, source-file inventory, protocol, game flows).

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn, websockets, PyYAML, SQLite (live world state), cryptography (self-signed TLS)
- **Frontend**: Vanilla JavaScript (ES modules), Three.js for the 3D board renderer
- **Testing**: Python `unittest`, Node `--test` runner, Playwright (browser flows + visual snapshots)
- **Dev tooling**: npm scripts, PowerShell launcher, vendored browser deps

## Directory Structure

| Path | Purpose |
| --- | --- |
| `server/` | Backend — accounts, protocol, services, commands, persistence, content loaders |
| `server/services/` | Rooms, cards, activities business logic |
| `server/state/` | SQLite world-state model and migrations |
| `server/commands/` | Command parser, registry, core command implementations |
| `server/client/` | Client-side logic ported to Python for browser-free tests |
| `app/` | Browser UI — JavaScript modules, Three.js renderer, HTML/CSS |
| `activities/` | Self-contained game activities (e.g. Sticker Designer) |
| `data/` | Shared card definitions and sticker artwork assets |
| `worlds/tutorial/` | Tutorial world YAML definitions (rooms, peeps, cards, recipes, props) |
| `tests/` | Python unit/integration tests, ported client-logic tests, and Playwright browser specs |

## Code Conventions

- **Python**: Type hints on all public functions. First-party source files kept under 1200 lines per codebase rule (static check). No inline comments unless necessary to explain tricky logic. Imports: standard library, third-party, then local `server.*` — ordered groups separated by blank line. Use `from __future__ import annotations` at the top of every Python file.
- **JavaScript**: Vanilla ES modules (`"type": "module"` in package.json). No build step for app code; only Three.js is version-pinned and Playwright is dev-only.
- **YAML**: World definitions are authored as human-readable YAML files under `worlds/` and `data/`. Never edit these by hand without validating structure against the content loaders in `server/content/`.
- **Naming**: Keep classes, modules, and functions descriptive. Avoid abbreviations beyond established ones (e.g. `peep`, `prop`).

## Running Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci
npm run vendor
$env:TRSERVER_NEW_ACCOUNT_PASSPHRASE = "choose-an-invitation"
$env:TRSERVER_FEATURES = "dev_sample_activity"
python run.py
```

Open **https://127.0.0.1:5000** and accept the local dev certificate. The launcher auto-generates a 14-day self-signed cert under `.local/`.

Environment variables (see README.md Configuration table):

| Variable | Required? | Default |
| --- | --- | --- |
| `TRSERVER_NEW_ACCOUNT_PASSPHRASE` | Yes | — |
| `TRSERVER_HOST` | No | `127.0.0.1` |
| `TRSERVER_PORT` | No | `5000` |
| `TRSERVER_USERS_PATH` | No | `users` |
| `TRSERVER_WORLD_PATH` | No | `worlds/tutorial` |
| `TRSERVER_WORLDSTATE_PATH` | No | `.local/worldstate.sqlite3` |
| `TRSERVER_FEATURES` | No | _(none)_ |
| `TRSERVER_TIMEZONE` | No | `UTC` |

## Testing

Run tests from an activated virtual environment.

### Python (server + client logic)
```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

### Browser flows + visual snapshots
```powershell
npx playwright install chromium       # or Chromium family browser of choice
npm run test:browser                  # functional tests
npm run test:visual                   # screenshot comparison
```

### Full suite
```powershell
python -m unittest discover -s tests -v   # server + client logic
npm test                                  # browser flows
```

### Visual baselines (manual review required)

Visual tests compare rendered boards and UI against PNG snapshots. They never auto-approve changes.

```powershell
$env:TR_BROWSER_CHANNEL = "chrome"    # match baseline environment
$env:TR_UPDATE_SCREENSHOTS = "1"      # explicit opt-in, only after manual design review
npm run test:visual -- --update-snapshots
Remove-Item Env:TR_UPDATE_SCREENSHOTS
```

Review generated `tests\browser\baselines` PNGs against `doc/design.md` and `doc/images/` references before committing. Then re-run **without** the update flag to confirm clean pass.

## Testing Architecture

Each browser test spins up a fresh HTTPS Python subprocess on an OS-assigned loopback port with isolated users and SQLite in its own `.browser-runtime\run-*` directory. No live server or shared state is used. Test failures retain Playwright traces, screenshots, and server logs in `test-results/`.

Browser harness settings (from `playwright.config.js`):
- Two projects: desktop (1280×800) and portrait (390×844 mobile touch)
- Fixed locale (`en-US`), timezone (`UTC`), reduced motion, SVG shader background for determinism
- Software WebGL via `--use-angle=swiftshader`, single raster thread to prevent saturation
- Visual diff: max 100 pixels / threshold 0.15 per screenshot

## Writing New Tests

1. **Python**: Add a module under `tests/` using `unittest.TestCase`; no external test framework. Service tests should subclass `tests/common.py:ServiceTestCase` for an isolated profile/world database and shared content.
2. **Client logic**: Port applicable modules from `app/js/` to `server/client/` and add matching tests under `tests/client/`, using `unittest.TestCase`. Name files `test_*.py`.
3. **Browser functional**: Edit `tests/browser/flows.spec.js`. Tests should use semantic selectors or stable IDs rather than pixel coordinates. Each test owns a fresh server fixture via helpers in `fixtures.js`.
4. **Visual screenshots**: Add to `tests/browser/screenshots.spec.js` when capturing rendered board/UI states matters. Baselines live in `tests/browser/baselines/`. Always review before committing.

## Key Design Decisions

- **Authoritative server**: All world state lives in SQLite on the server. The client is a pure renderer + input dispatcher.
- **In-process room ordering**: A single server process owns a world, so room broadcasts are ordered by the event loop; there is no per-room sequence counter. Command results are matched to clients by `request_id`.
- **Invitation-gated accounts**: `TRSERVER_NEW_ACCOUNT_PASSPHRASE` controls who can register. Changing it after accounts exist has no effect on existing users.
- **Feature flags**: The `TRSERVER_FEATURES` env var gates optional behavior (`dev_sample_activity`, etc.). Never ship enabled-by-default dev features to production.
- **Hot-reload disabled in prod**: A separate production launch path (not yet implemented) would use a different certificate and disable self-signed cert generation.

## Modifying World Content

1. Edit YAML files under `worlds/<world>/` or `data/`. Validated by loaders in `server/content/worlds.py` and `server/content/cards.py`.
2. After changes, run browser tests against the modified world: `npm run test:browser -- -g "<test name>"`.
3. Never modify checked-in visual baselines to mask content bugs. Regenerate visuals only when the change is intentional and matches design docs.

## Before You Commit / PR

- [ ] All automated tests pass locally: `npm test` + Python unittests
- [ ] Server static checks still clear (under-1200-line rule, no fragile CSS assertions in static checks)
- [ ] New visual baselines are reviewed against `doc/design.md` and approved
- [ ] No secrets or keys added (the self-signed cert under `.local/` remains gitignored)
- [ ] World YAML edits validated by running the game client manually
