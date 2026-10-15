# Tinyrooms

Tinyrooms is a multiplayer miniature-world game built with FastAPI, vanilla
JavaScript, and Three.js. See [architecture](doc/architecture.md) for components,
protocol, game flows, and source layout; [AGENTS.md](AGENTS.md) for contributor rules.

## Quick Start

Requires Python 3.11+ and Node.js 20+. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci
npm run vendor
$env:TRSERVER_NEW_ACCOUNT_PASSPHRASE = "choose-an-invitation"
$env:TRSERVER_MODS = "*"
python run.py
```

With an activated Python environment, Bash users can run `./setup.sh` once,
then `./start.sh`. [start.sh](start.sh) supplies **local-development** invitation,
mod, editor, and MC credential defaults; override them for real deployments.

Open **https://127.0.0.1:5000** and accept the development certificate.
[run.py](run.py) stores a 14-day self-signed certificate under `.local/`; it is
not appropriate for public hosting. For a phone on a trusted LAN, run
`python run.py --host 0.0.0.0` and use the machine's LAN address. Expose the port
only on trusted networks.

## Configuration

[server/config.py](server/config.py) is the complete world-server configuration
reference (environment parsing, defaults, validation, and feature names).
Common overrides are `TRSERVER_HOST`/`PORT` (loopback/5000), `TRSERVER_USERS_PATH`
(`users`), `TRSERVER_WORLD_PATH` (`worlds/tutorial`), and `TRSERVER_WORLDSTATE_PATH`
(`.local/worldstate.sqlite3`). `TRSERVER_NEW_ACCOUNT_PASSPHRASE` is required for
registration; changing it does not affect existing accounts.

Use `TRSERVER_FEATURES` for optional tools, `TRSERVER_ADMINS` for bootstrap admin
usernames, and `TRSERVER_MODS` for mod selection. Reverse-proxy deployments can
set `TRSERVER_BASE_PATH` and additional `TRSERVER_PUBLIC_ORIGIN` values.
MC configuration, shared content, identity, and TLS settings are documented in
[Mission Control](doc/mission-control.md#3-configuration).

## Dynamic Peeps

The [dynamic-peeps specification](doc/dynamic-peeps.md) describes planned
LLM-regenerated NPC behavior/dialogue, a separate generation worker, and its
configuration/content examples. The current feature parser does not accept
`dynamic_peeps`.

> [!WARNING]
> The design executes **agent-generated Python inside the game-server process**.
> It is dev-only and **not safe for production**. Read the blocking hardening
> gate in the specification's §9 before implementing or enabling it.

## Mission Control

MC optionally serves public player entry at `/`, operator administration at
`/mission-control`, and fleet/shared-profile management. `run.py` selects MC
when `TRSERVER_FEATURES` includes `mission-control`:

```powershell
$env:TRSERVER_FEATURES = "mission-control"
$env:TRSERVER_MC_PASSPHRASE = "operator-passphrase"
$env:TRSERVER_MC_TOKEN = "shared-secret"
$env:TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE = "choose-an-invitation"
python run.py
```

Open **https://127.0.0.1:8001/mission-control** for operators, or
**https://127.0.0.1:8001/** for players. Bash users can run
`TRSERVER_FEATURES=mission-control ./start.sh`; set `TRSERVER_ADMIN_ENV` to load
an environment file before its development defaults.

Start a world and select **Make default** before creating players. Worlds use
direct HTTPS ports on the same hostname as entry and share MC's profile DB.
See the canonical [entry rules](doc/mission-control.md#21-player-entry-and-destination-resolution),
[lifecycle controls](doc/mission-control.md#53-server-manager), and
[durable state](doc/mission-control.md#41-runtime-state-and-persisted-launch-settings).

## Deploying

[tools/deploy.py](tools/deploy.py) deploys over passwordless SSH:

```bash
python tools/deploy.py <host> [rootdir] [bootstrap|deploy] [-u USER] [--dirty] [--keep-version]
```

`host` accepts `user@host`; `-u` overrides the user. `bootstrap` (default) prepares
nginx/TLS, directories, dependencies, and cron keepalive, then deploys a version.
`deploy` bumps the patch version, packages the working tree, uploads it, and
repoints `versions/latest`. `--dirty` skips the clean-tree check/tagging and marks
the version dirty. `--keep-version` overwrites the newest recorded release
locally/remotely and defaults to `deploy` when no operation is specified.

Read [deployment and upgrade instructions](doc/mission-control.md#83-deployment-and-upgrades)
before hosting or upgrading: they cover direct world ports, certificates,
firewalls, secrets, resumable uploads, and migration of saved legacy launch
settings. Deployment does not open firewalls or automatically migrate instances.

## Mods

Mods under `mods/` (override `TRSERVER_MODS_PATH`) use a `mod.yaml` manifest and
may contribute content, props, activity iframes, and Python `register(api)`
behavior. Enable comma-separated names or `*` through `TRSERVER_MODS`. Worlds
declare `requires_mods`; the tutorial requires `infinite-bedrooms`.

## Editors

Enable tools with `TRSERVER_FEATURES`; powers are also required:

- `world-editor` at `/world-editor`, and read-only `card-database` at
  `/card-database`: `builder`, `game-master`, or `admin`.
- `prop-editor` at `/prop-editor`: `admin`; edits loaded world/mod/shared prop
  definitions and `data/fx` effect stacks. Saves rewrite backing YAML without
  preserving comments. Use **Save prop/effect**, then **Reload world** to publish.

For example, set `$env:TRSERVER_FEATURES = "prop-editor"` and
`$env:TRSERVER_ADMINS = "siteadmin"` before `python run.py`.

## Verification

Activate the virtual environment first so vendoring uses its Python:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
npm run vendor
npx playwright install chromium
python -m unittest discover -s tests -v
npm test
```

[package.json](package.json) defines `test:client` (actual JS modules via Node),
`test:browser` (minimal Playwright smoke), `test:visual` (rendered states), and
`test:perf` ([separate performance budgets](doc/performance.md)). `npm test` runs
client + browser tests. Target smoke with `npm run test:browser -- -g "all core cards"`.

### Troubleshooting

- The browser harness auto-selects `.venv\Scripts\python.exe`; override with
  `$env:TR_TEST_PYTHON = "C:\path\to\python.exe"` if needed.
- If browser downloads fail, use installed Chrome/Edge with
  `$env:TR_BROWSER_CHANNEL = "chrome"` (or `"msedge"`).
- “No supported WebSocket library detected” and `/ws` returning 404: reinstall
  `requirements-dev.txt` and restart the server. It includes runtime requirements
  and `websockets`; bare `uvicorn` is not a complete runtime installation.
- MC destination failures: follow [entry checks](doc/mission-control.md#21-player-entry-and-destination-resolution)
  and [upgrade warnings](doc/mission-control.md#83-deployment-and-upgrades).

### Playwright tests and reference screenshots

Run `npm run test:visual` separately; functional tests never update screenshots.
The checked-in baseline uses Windows/Chrome (`$env:TR_BROWSER_CHANNEL = "chrome"`).
Set `$env:TR_VISUAL_ONLY = "onboarding,self"` for selected images and remove it
with `Remove-Item Env:TR_VISUAL_ONLY` for the full matrix.

Only after manual design review and approval (see [baseline rules](AGENTS.md#visual-baselines-manual-review-required)):

```powershell
$env:TR_UPDATE_SCREENSHOTS = "1"
npm run test:visual -- --update-snapshots
Remove-Item Env:TR_UPDATE_SCREENSHOTS
npm run test:visual
```

## Project layout

See [architecture](doc/architecture.md) for the source map and
[cutscenes](doc/cutscenes.md) for core/world script placement. Design and visual
references live under [doc/](doc/).
