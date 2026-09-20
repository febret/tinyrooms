# Tinyrooms — Milestone 1

Tinyrooms is a multiplayer miniature-world game built with FastAPI, vanilla
JavaScript, and Three.js. This repository currently implements the secure,
persistent Milestone 1 vertical slice described in
[doc/milestone-1.md](doc/milestone-1.md). The technical architecture
(components, source files, protocol, game flows) is documented in
[doc/architecture.md](doc/architecture.md).

## Included

- Invitation-gated account creation and secure rotating sessions.
- Mandatory initial Sticker Designer activity.
- Persistent profiles and separate SQLite world state.
- Authoritative, versioned WebSocket commands and sequenced room events.
- Multiplayer presence and styled room chat.
- Hub/Playroom navigation.
- Room and inventory card inspection, quantity pickup/drop, and favorites.
- Responsive Three.js board, activity windows, sounds, and keyboard/touch UI.
- A feature-gated sample activity for lifecycle testing.

Later tutorial rooms load and validate as content, but their progression,
behaviors, editors, and advanced gameplay remain outside Milestone 1.

## Run locally

Python 3.11+ and Node.js 20+ are required. From PowerShell:

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

Open **https://127.0.0.1:5000** and accept the local development certificate.
The launcher stores a 14-day self-signed certificate under `.local`; it is not
appropriate for public hosting.

The server defaults to loopback. For a phone on a trusted local network, run
`python run.py --host 0.0.0.0` and use the machine's LAN address. Only expose
the port on trusted networks.

## Configuration

| Variable | Purpose |
| --- | --- |
| `TRSERVER_NEW_ACCOUNT_PASSPHRASE` | Required invitation for account creation |
| `TRSERVER_USERS_PATH` | Profile directory; defaults to `users` |
| `TRSERVER_WORLD_PATH` | Loaded definitions; defaults to `worlds/tutorial` |
| `TRSERVER_WORLDSTATE_PATH` | Live SQLite state; defaults to `.local/worldstate.sqlite3` |
| `TRSERVER_FEATURES` | Optional flags such as `dev_sample_activity` |
| `TRSERVER_TIMEZONE` | Game timezone; defaults to `UTC` |
| `TRSERVER_HOST` | Listener address; defaults to `127.0.0.1` |
| `TRSERVER_PORT` | HTTPS port; defaults to `5000` |

Profile and SQLite paths are never mounted as static content. Back up both the
profile directory and world-state database to preserve accounts and room state.

## Playing the vertical slice

- Drag the board to rotate; scroll or pinch to zoom.
- Select a card or peep to show its description and server-provided actions.
- Use Room to inspect the Playroom's sample card and pick it up.
- Use Inventory to inspect or drop owned cards.
- Use the chat bar for room chat or dot commands. `(.)` and `(!)` select bubble
  styles.
- The command menu lists the available commands.
- With `dev_sample_activity` enabled, enter `.play sample` to exercise the
  activity window.

## Verification

Activate the virtual environment first so `npm run vendor` uses its Python.
No additional Python test framework is required:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
npm run vendor
npx playwright install chromium
python -m unittest discover -s tests -v
npm run test:browser
```

`npm test` runs the Playwright functional browser tests.
For a targeted run use `npm run test:browser -- --project=portrait -g "quantity"`.
The browser harness uses `.venv\Scripts\python.exe` automatically; override with
`$env:TR_TEST_PYTHON = "C:\path\to\python.exe"` if needed.
If browser downloads are unavailable, an installed Chrome or Edge can run
functional checks with `$env:TR_BROWSER_CHANNEL = "chrome"` (or `"msedge"`).
Install Playwright's own browsers with `npm run install:browsers` (it accepts the
usual arguments, for example `npm run install:browsers -- chromium --force`).
Prefer it over `npx playwright install`: on networks that advertise an IPv6
default route without a working global IPv6 address, Playwright's downloader
tries the black-holed IPv6 address first and fails with
`Request to https://cdn.playwright.dev/... timed out after 30000ms` instead of
falling back to IPv4. The wrapper resolves hosts to IPv4 when available.
The checked-in visual baselines were reviewed and captured on Windows using
Chrome **152.0.7977.83**. Use `$env:TR_BROWSER_CHANNEL = "chrome"` to compare that
baseline environment. Chromium/Edge or a different browser version, OS, or font
set may render differently and require separately reviewed baselines; do not
automatically accept those differences. Functional tests can use any of these
Chromium-family channels. To return to Playwright's bundled Chromium, use
`Remove-Item Env:TR_BROWSER_CHANNEL`.

The current matrix contains 40 Python tests (17 client-logic, 14 server, five
launcher, four static/UI), eight functional browser cases (three desktop and
five portrait), and two visual scenarios capturing 20 images each. Visual comparison remains a separate,
explicitly reviewed step.

`requirements-dev.txt` includes the runtime requirements, including the explicit
`websockets` dependency required by Uvicorn. If logs report “No supported WebSocket
library detected” and `/ws` returns 404, restore dependencies with
`python -m pip install -r requirements-dev.txt`, then restart that server.
Installing bare `uvicorn` alone is not a complete Tinyrooms runtime setup.

### Isolation and diagnostics

Every browser test owns a fresh HTTPS Python child process, an OS-assigned
loopback port, test certificates, users, and SQLite state in a unique
`.browser-runtime\run-*` directory. It uses the existing server app/config and
launcher certificate helper with UTC and `dev_sample_activity`. World definitions
and static assets are read from the repository; **live `users` and `.local`
databases/certificates are never used**. No existing server is reused or killed.
Readiness is checked over HTTPS. Closing the fixture's stdin shuts down its
server, with a bounded fallback that kills only that owned child; its directory
is removed even on test failure. A forcibly terminated test runner may leave a
`run-*` directory, which can be deleted after confirming that run has stopped.

Failures retain screenshots, Playwright traces, and server logs in `test-results`;
`npm run test:report` opens the HTML report from `playwright-report`. These output
directories and runtime data are ignored. Tests fail on uncaught page/iframe
exceptions and failed static-asset responses; they do not swallow them.
Browser runs cap animation frames at five per second and Chromium raster work
at one thread to keep software WebGL from
saturating the host. Board helpers are tested for coordinate
mapping and visual-change detection; camera fitting is covered by browser frame
checks.
Static Python checks cover asset wiring, API contract references, and the
under-1200-line first-party source limit, not fragile CSS formatting strings.

### Visual reference matrix and baseline approval

Run `npm run test:visual` separately; functional tests never update screenshots.
For the checked-in Windows/Chrome baseline:

```powershell
$env:TR_BROWSER_CHANNEL = "chrome"
npm run test:visual
```

To recheck only particular images while exercising the same real gameplay flow,
set `$env:TR_VISUAL_ONLY = "onboarding,self"` before running the visual command.
Remove it with `Remove-Item Env:TR_VISUAL_ONLY` for the complete matrix.

Both projects use real HTTPS/WebSocket gameplay:

| Scenario | Desktop 1280×800 | Portrait 390×844 |
| --- | --- | --- |
| Login / mandatory Sticker Designer | auth, onboarding | auth, onboarding |
| Teal board, peeps, favorite/expanded hand, compact dock | main, expanded-core, playroom-main | main, expanded-core, playroom-main |
| Room overlay and book inspection | room, details | room, details |
| Quantity interaction / owned card grouping | quantity, inventory | quantity, inventory |
| Selected peep / normal, thought, spiky messages | peep, three bubbles | peep, three bubbles |
| Sample activity window and iframe | activity | activity |
| Existing Emotes/Skills/Journal/Self/Friends screens | five views | five views |
| Visible command failure feedback | error-toast | error-toast |

Functional coverage additionally checks creation/login errors, onboarding
restrictions, two-context presence/chat/travel, core expansion/favorites,
placeholder views, transfer cancel/Escape, pickup/drop, overlay hit blocking,
command-menu insertion, persisted log preference, invalid commands, and activity
minimize/maximize/close, mouse drag/wheel, and touch drag/two-finger pinch. Camera
checks compare settled rendered frames and ensure gestures do not select entities.
Tests use semantic labels or stable IDs, not pixel clicks for gameplay.
Geometry checks cover overflow, viewport containment, and 44px
primary controls at both sizes.

Screenshot comparison uses a fixed wall clock, UTC, English locale, reduced
motion, software WebGL, stable test names/content, and decoded image/font
readiness. It compares the actual board and UI without hiding them behind masks.
Use the same OS, browser version/channel, and fonts when comparing baselines.
Missing baselines fail and produce candidate actual images; they never silently
pass. **Review every candidate against `doc/design.md` and applicable
`doc/images` references before approving it**, including mobile adaptation,
card artwork, board composition, book, peeps, and control overlap. A successful
baseline write is not design approval.

Only after that manual review, opt in explicitly:

```powershell
$env:TR_UPDATE_SCREENSHOTS = "1"
npm run test:visual -- --update-snapshots
Remove-Item Env:TR_UPDATE_SCREENSHOTS
npm run test:visual
```

Review the resulting `tests\browser\baselines` PNG changes again and commit only
approved images. The final command must compare without the update flag. Never
refresh baselines just to make a regression pass. No baselines are automatically
approved by the harness.

### Manual review

After automated checks, review the game in an ordinary desktop browser and on
a real phone. Browser touch emulation does not replace checking the native
on-screen keyboard, safe areas, audio permissions, or two-finger gestures.

- Create an account and finish the required Sticker Designer; reload before
  confirming once to check that onboarding resumes.
- Rotate and zoom the Hub/Playroom, then inspect and transfer a card.
- Check card proportions, selection glow, card sounds, and readable details.
- Send normal, `(.)` thinking, and `(!)` spiky chat, then dismiss each bubble.
- Open Room/Inventory and verify that peeps, actions, and chat remain usable.
- Open `.play sample` with `dev_sample_activity` enabled and check its window
  controls, including after rotating the phone.

## Project layout

- `app`: browser UI and Three.js tabletop renderer.
- `server`: accounts, commands, protocol, services, and persistence.
- `activities`: Sticker Designer and activity fixtures.
- `data`: shared cards and sticker artwork.
- `worlds/tutorial`: tutorial definitions and assets.
- `tools`: reproducible browser dependency vendoring.
- `doc`: design, milestone, and visual references. Start with
  [doc/architecture.md](doc/architecture.md) for the technical overview.
