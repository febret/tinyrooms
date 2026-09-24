# Tinyrooms — Milestone 1

Tinyrooms is a multiplayer miniature-world game built with FastAPI, vanilla
JavaScript, and Three.js. This repository currently implements the secure,
persistent Milestone 1 vertical slice described in
[doc/milestone-1.md](doc/milestone-1.md). The technical architecture
(components, source files, protocol, game flows) is documented in
[doc/architecture.md](doc/architecture.md).

## Quick Start

Python 3.11+ and Node.js 20+ are required. From PowerShell:

```bash
# Installs all required dependencies - run once
./setup.sh
# Starts a local server on https://127.0.0.1:5000
./start.sh
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
| `TRSERVER_CUSTOM_STICKERS_PATH` | Rendered custom peep stickers; defaults to `.local/stickers` |
| `TRSERVER_FEATURES` | Optional flags such as `dev_sample_activity` |
| `TRSERVER_MODS` | Comma-separated mod names to load, or `*` for every installed mod |
| `TRSERVER_MODS_PATH` | Mod search directory; defaults to `mods` |
| `TRSERVER_ADMINS` | Comma-separated usernames bootstrapped with the `admin` power |
| `TRSERVER_TIMEZONE` | Game timezone; defaults to `UTC` |
| `TRSERVER_HOST` | Listener address; defaults to `127.0.0.1` |
| `TRSERVER_PORT` | HTTPS port; defaults to `5000` |
| `TRSERVER_MC_ENDPOINT` | `host:port` of the mission-control server; enables the world's `/api/mc/*` client |
| `TRSERVER_MC_TOKEN` | Shared secret for the mission-control channel (required with `TRSERVER_MC_ENDPOINT`) |
| `TRSERVER_MC_NAME` | Display name for this instance; defaults to `world_id@host:port` |
| `TRSERVER_MC_CA_FILE` | PEM CA bundle used to verify the mission-control server certificate |
| `TRSERVER_MC_INSECURE_TLS` | Dev-only: skip mission-control certificate verification |

## Mission Control

Mission control is an optional operations server for managing a fleet of world
servers and the shared profile database. See
[doc/mission-control.md](doc/mission-control.md) for the full specification.

There is a single entry point: `run.py` launches mission control instead of the
world server when `TRSERVER_FEATURES` includes `mission-control`.

```powershell
$env:TRSERVER_FEATURES = "mission-control"
$env:TRSERVER_MC_PASSPHRASE = "operator-passphrase"
$env:TRSERVER_MC_TOKEN = "shared-secret"
python run.py
```

On Linux/macOS the same works through `start.sh`, which supplies local
development defaults for the passphrase and token:

```bash
TRSERVER_FEATURES=mission-control ./start.sh
```

Open **https://127.0.0.1:8001/mission-control** and sign in with the operator
passphrase. Mission control serves HTTPS with the same self-signed certificate
helper as the game server (reusing `.local/cert.pem` / `key.pem`).

| Variable | Purpose |
| --- | --- |
| `TRSERVER_FEATURES` | Must include `mission-control` |
| `TRSERVER_MC_PASSPHRASE` | Required operator login passphrase |
| `TRSERVER_MC_TOKEN` | Required shared secret for the MC ↔ world channel |
| `TRSERVER_MC_HOST` | Listener address; defaults to `127.0.0.1` |
| `TRSERVER_MC_PORT` | HTTPS port; defaults to `8001` |
| `TRSERVER_MC_USERS_PATH` | Profile DB directory to manage; defaults to `users` |
| `TRSERVER_MC_INSTANCES_PATH` | Runtime dirs for MC-spawned servers; defaults to `.local/mc-instances` |
| `TRSERVER_MC_VERSIONS_PATH` | Extra server checkouts to inventory; defaults to `.local/mc-versions` |
| `TRSERVER_MC_CA_FILE` | PEM CA bundle used to verify world-server TLS |
| `TRSERVER_MC_INSECURE_TLS` | Dev-only: skip world-server cert verification |
| `TRSERVER_MC_HEARTBEAT_SECONDS` | Expected heartbeat interval; defaults to `5` |
| `TRSERVER_MC_ACTOR` | World username used as the admin-console actor; defaults to `mission-control` |
| `TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE` | Invitation used for MC-spawned worlds; generated when unset |

## Mods

Server mods live under `mods/` (override with `TRSERVER_MODS_PATH`). A mod is a
directory containing a `mod.yaml` manifest that may contribute world content
(`content/`), a props set (`props/`), activity iframes (`activities/`), and
Python behaviour through an entrypoint (`mod.py`) exposing `register(api)`.
Enable mods with `TRSERVER_MODS` (comma-separated names, or `*` for every
installed mod). Worlds declare the mods they need with `requires_mods` in
`world.yaml`; the tutorial world requires `infinite-bedrooms`.

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

`requirements-dev.txt` includes the runtime requirements, including the explicit
`websockets` dependency required by Uvicorn. If logs report “No supported WebSocket
library detected” and `/ws` returns 404, restore dependencies with
`python -m pip install -r requirements-dev.txt`, then restart that server.
Installing bare `uvicorn` alone is not a complete Tinyrooms runtime setup.

### Playwright tests and reference screenshots

Run `npm run test:visual` separately; functional tests never update screenshots.
For the checked-in Windows/Chrome baseline:

```powershell
$env:TR_BROWSER_CHANNEL = "chrome"
npm run test:visual
```

To recheck only particular images while exercising the same real gameplay flow,
set `$env:TR_VISUAL_ONLY = "onboarding,self"` before running the visual command.
Remove it with `Remove-Item Env:TR_VISUAL_ONLY` for the complete matrix.

To update the baseline screenshots:

```bash
TR_UPDATE_SCREENSHOTS=1 npm run test:visual -- --update-snapshots
```


## Project layout

- `app`: browser UI and Three.js tabletop renderer.
- `server`: accounts, commands, protocol, services, and persistence.
- `activities`: Sticker Designer and activity fixtures.
- `data`: shared cards and sticker artwork.
- `worlds/tutorial`: tutorial definitions and assets.
- `tools`: reproducible browser dependency vendoring.
- `doc`: design, milestone, and visual references. Start with
  [doc/architecture.md](doc/architecture.md) for the technical overview.
