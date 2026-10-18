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

## Multiworld

[Bash users] `./start_multiworld.sh` starts a local Mission Control plus the
tutorial and scammon-academia world servers sharing one profile database and
one advertised hostname. The tutorial hub portal and the scammon-academia hall
portal link the two worlds. It uses development credentials and self-signed
certificates; override `MC_PORT`, `TUTORIAL_PORT`, `SCAMMON_PORT`, or
`PUBLIC_HOST` as needed.

```bash
./start_multiworld.sh
# Mission Control:  https://127.0.0.1:8001/mission-control
# Tutorial world:   https://127.0.0.1:5100/
# Scammon Academia: https://127.0.0.1:5101/

# To accept connections from other machines, pass a reachable address. This also
# binds the three listeners to 0.0.0.0; the browser uses the advertised host so
# the shared session cookie keeps working across ports:
./start_multiworld.sh --public-host 192.168.1.50
```

Author cross-world exits in a room's `rooms.yaml` with `target_world: <world-id>`
and an optional `target: <room>` (defaulting to the destination world's entry
room). Both worlds must share a profile database, advertise client URLs on
Mission Control's hostname, and be connected to the same Mission Control
instance. See [fleet destination discovery](doc/mission-control.md#7-mission-control-ui-api).

## Deploying

[tools/deploy.py](tools/deploy.py) deploys over passwordless SSH:

```bash
python tools/deploy.py <host> [rootdir] [-u USER] [--dirty] [--keep-version]
```

`host` accepts `user@host`; `-u` overrides the user. The default root is
`~/tinyrooms`. The same command prepares a fresh host or updates an existing
installation: it ensures nginx/TLS, directories, and the Python environment,
uploads a release, installs dependencies, refreshes configuration and cron
keepalive, then repoints `versions/latest` and restarts Mission Control once.
It reports success only after the expected MC version answers its session API
and the operator passphrase sourced from `admin.env` establishes a session.
Existing TLS files, secrets, and supported operator settings are preserved.
`--dirty` skips the clean-tree check/tagging and marks the version dirty.
`--keep-version` (also `--keepversion`) overwrites the newest recorded release locally/remotely instead
of bumping the patch version.

There is no separate `bootstrap`/`deploy` argument. For an existing installation
under the former default, pass `~/.local/tinyrooms` explicitly; changing the
default does not move existing data.

Read [deployment and upgrade instructions](doc/mission-control.md#83-deployment-and-upgrades)
before hosting or upgrading: they cover direct world ports, certificates,
firewalls, secrets, resumable uploads, and migration of saved legacy launch
settings. Deployment does not open firewalls or automatically migrate instances.

### Firewall settings
To open ports used by multi-world tinyroom setups on google cloud use the gcloud CLI like in the example below:
```
gcloud compute instances add-tags tinyrooms-w1 \
  --project=tinyrooms \
  --zone=us-east5-a \
  --tags=tinyrooms-worlds

gcloud compute firewall-rules create tinyrooms-worlds \
  --project=tinyrooms \
  --network=default \
  --direction=INGRESS \
  --allow=tcp:10000-10999 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=tinyrooms-worlds
```

## Mods

Mods under `mods/` (override `TRSERVER_MODS_PATH`) use a `mod.yaml` manifest and
may contribute content, props, activity iframes, and Python `register(api)`
behavior. Enable comma-separated names or `*` through `TRSERVER_MODS`. Worlds
declare `requires_mods`; the scammon-academia world requires `classrooms`.

## Editors

Enable tools with `TRSERVER_FEATURES`; powers are also required:

- `world-editor` at `/world-editor`, and read-only `card-database` at
  `/card-database`: `builder`, `game-master`, or `admin`.
- `prop-editor` at `/prop-editor`: `admin`; edits loaded world/mod/shared prop
  definitions and `data/fx` effect stacks. Saves rewrite backing YAML without
  preserving comments. Use **Save prop/effect**, then **Reload world** to publish.

For example, set `$env:TRSERVER_FEATURES = "prop-editor"` and
`$env:TRSERVER_ADMINS = "siteadmin"` before `python run.py`.

## Baking assets

Props and card art are generated by the sibling `../delphi-comfyui` checkout,
which drives the remote ComfyUI that turns prompts into GLB props, card PNGs,
and sounds. Each `bake.json` (`data/propsets/*/bake.json`,
`worlds/*/cards/bake.json`) lists those generation tasks in the format
documented by `../delphi-comfyui/bake-skill.md`.

[tools/bake_assets.py](tools/bake_assets.py) wraps `bake.py` for this repo:

```bash
python tools/bake_assets.py data/propsets/base/bake.json
python tools/bake_assets.py --filter '*-rug' --progress
python tools/bake_assets.py --force          # re-render everything
python tools/bake_assets.py --reseed --dryrun
```

With no paths it discovers every `bake.json` under `data/` and `worlds/`.
`--filter GLOB` bakes a subset, `--progress` shows a bar, `--dryrun` previews
without writing anything, and `--force` re-renders outputs that already exist.
`--reseed` assigns fresh random integers to pinned `args.seed` values in the
input JSON (preserving its formatting) and forces those assets to regenerate, so
a run produces new variations. Set `TR_BAKE_DIR` to use a different
`../delphi-comfyui` location.

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
`test:browser` (minimal Playwright smoke), and
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

## Project layout

See [architecture](doc/architecture.md) for the source map and
[cutscenes](doc/cutscenes.md) for core/world script placement. Design and visual
references live under [doc/](doc/).
