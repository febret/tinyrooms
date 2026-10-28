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
Whiteboard PNG uploads are stored as content-addressed files under
`TRSERVER_WHITEBOARD_IMAGES_PATH` (default `.local/whiteboards`). Pre-image
vector whiteboards are only read and converted when legacy support is enabled:

```powershell
python run.py --legacy-features svg-boards
```

`TRSERVER_LEGACY_FEATURES=svg-boards` selects the same compatibility mode.

Gameplay tuning can be loaded from an optional `options.json` without editing
core content. Pass it with `--options` or `TRSERVER_OPTIONS_PATH`:

```powershell
python run.py --options .local/options.json
```

The file can disable Energy, Sickness, and Cleanliness mechanics, toggle the
Sickness/Cleanliness dynamic card drops independently, and override the
mechanic-tied constants (recharge rates, base maxima, Energy costs, drop
cadence/chance/room cap, and vibe penalties). Missing fields keep core defaults
and unknown fields are rejected. MC configuration, shared content, identity, and
TLS settings are documented in
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

Start a world and select **Make default** before creating players. In local
development, worlds use direct HTTPS ports on the same hostname as entry and
share MC's profile DB; deployed instances use same-origin `/world/<id>/` paths.
See the canonical [entry rules](doc/mission-control.md#21-player-entry-and-destination-resolution),
[lifecycle controls](doc/mission-control.md#53-server-manager), and
[durable state](doc/mission-control.md#41-runtime-state-and-persisted-launch-settings).

## Multiworld

[Bash users] `./start_multiworld.sh` starts a local Mission Control plus the
worlds listed in [multiworld.json](multiworld.json), sharing one profile
database and one advertised hostname. Edit that JSON file to choose the fleet:
world entries are skipped when they set `"enabled": false`; each `worlds`
entry may be a world id string or an object with `id` plus optional `enabled`,
`port`, `instance_id`, `label`, and `mods`; a `path` may point the
world at a directory outside `worlds/` (for example a sibling workshop
checkout), with an optional `shared_content` root layered in for that world's
own cardsets/propsets. The top-level `mods` list applies by default. [`start_multiworld.py`](start_multiworld.py) reads the file
and manages the child servers. It uses development credentials and self-signed
certificates; override `MC_PORT` or `PUBLIC_HOST` as needed, and per-world ports
with `MULTIWORLD_<WORLD>_PORT` or the legacy `TUTORIAL_PORT`, `SCAMMON_PORT`,
`ARCADE_PORT`, `TINYTOWN_PORT`, `BACKROOMS_PORT`, `VAULT_PORT`, and `BOBS_PORT`.

```bash
./start_multiworld.sh
# Mission Control:  https://127.0.0.1:8001/mission-control
# Tutorial world:   https://127.0.0.1:5100/
# Scammon Academia: https://127.0.0.1:5101/
# Tiny Arcade:      https://127.0.0.1:5102/
# TinyTown:         https://127.0.0.1:5103/
# Tiny Backrooms:   https://127.0.0.1:5104/
# Tiny Vault:       https://127.0.0.1:5105/
# Bob's Burgers:    https://127.0.0.1:5106/

# To accept connections from other machines, pass a reachable address. This also
# binds all listeners to 0.0.0.0; the browser uses the advertised host so the
# shared session cookie keeps working across ports:
./start_multiworld.sh --public-host 192.168.1.50

# Use an alternate fleet definition:
./start_multiworld.sh --config my-multiworld.json
```

Author cross-world exits in a room's `rooms.yaml` with `target_world: <world-id>`
and an optional `target: <room>` (defaulting to the destination world's entry
room). Both worlds must share a profile database, advertise client URLs on
Mission Control's hostname, and be connected to the same Mission Control
instance. See [fleet destination discovery](doc/mission-control.md#7-mission-control-ui-api).

## Deploying

[tools/deploy.py](tools/deploy.py) deploys over passwordless SSH:

```bash
python tools/deploy.py <host> [rootdir] [-u USER] [--content FILE] [--dirty] [--force] [--force-restart]
```

`host` accepts `user@host`; `-u` overrides the user. The default root is
`~/tinyrooms`. `--content` selects the deployment content file
(default `./multiworld.json`). Only worlds marked `"enabled": true` are
packaged, together with the mods, cardsets, and propsets their `world.yaml`
requires (`requires_mods`, `requires_cardsets`, `requires_propsets`; absent
cardset/propset declarations include the available content needed by those
worlds). Worlds and content may live outside `worlds/` or `data/` when their
content entry supplies `path`/`shared_content`. The same command prepares a
fresh host or updates an existing installation: it ensures nginx/TLS,
directories, and the Python environment, uploads a release, installs
dependencies, refreshes configuration and cron keepalive, then repoints
`versions/latest` and restarts Mission Control once.
It reports success only after the expected MC version answers its session API
and the operator passphrase sourced from `admin.env` establishes a session.
Existing TLS files, secrets, and supported operator settings are preserved.
Deployment serves worlds under the same origin at `/world/<instance-id>/`,
binds world listeners to loopback, and regenerates the nginx world map. Only
TCP 80 and 443 need public ingress. `--dirty` skips the clean-tree check and
packages uncommitted changes as-is.
The deploy script never modifies `version.json`: it ships the newest recorded
version. Cut a new release by editing `version.json` before deploying.
Packages are named `tinyrooms-<version>-<content-hash>.tar.gz`; the SHA-256
hash covers the selected worlds/mods/cardsets/propsets, so identical content
sets are identifiable across builds and Mission Control shows the hash for
running servers. If a local tarball or remote release/checkout already uses
that version, deployment stops with an error unless `--force` is given to
overwrite it.
Releases carry runtime code, content, and tools only: design docs (`doc/`),
test suites, and dev-only config are excluded to keep uploads small.
`--force-restart` (also `--forcerestart`) additionally rolls every running
*spawned* instance onto the deployed version before Mission Control itself
restarts: each such child is pointed at the new checkout and restarted, and
the script waits for it to report the new build. External instances cannot be
updated and are skipped with a warning; stopped instances are left untouched.
Deployment always restarts Mission Control once to activate the release, so
the flag adds the instance rollout, not an extra MC restart.
Console output uses animated spinners, a byte progress bar for the upload,
and colors when stdout is a TTY; otherwise it prints plain lines, and honors
`NO_COLOR`.

There is no separate `bootstrap`/`deploy` argument. For an existing installation
under the former default, pass `~/.local/tinyrooms` explicitly; changing the
default does not move existing data.

### Installing a CA-issued certificate

[tools/install_certificates.py](tools/install_certificates.py) replaces a host's
TLS pair with a purchased certificate bundle and refreshes nginx:

```bash
python tools/install_certificates.py -u febret tinyrooms.app --cert-dir .local/certificates
```

It discovers `<name>-certificate.crt`, `<name>-key.key`,
`<name>-intermediate.pem`, and `<name>-cross.pem` in the directory (override with
`--cert`, `--key`, `--chain`, and `--root`), uploads the leaf plus intermediates
as `server.crt`, verifies the key and chain, backs up the previous files and nginx
site under `~/tinyrooms/nginx/backups/`, and tests/reloads nginx. nginx
`server_name` defaults to the certificate's DNS SANs; add names such as the SSH
host with `--server-name`. Deploy with the public hostname so Mission Control's
advertised world URLs match the certificate.

Read [deployment and upgrade instructions](doc/mission-control.md#83-deployment-and-upgrades)
before hosting or upgrading: they cover certificates, firewalls, secrets,
resumable uploads, and migration of saved legacy launch settings. Deployment
does not open firewalls or automatically migrate instances.

### Installable app

The player entry page is an installable Chrome PWA. It serves
`/manifest.webmanifest`, install icons, a service worker with an offline entry
fallback, and an **Install app** button. Install from `https://<public-host>/`;
because worlds live under `/world/<instance-id>/` on the same origin, gameplay
stays inside the installed app.

### Firewall settings

Only public TCP **80** and **443** are required. World servers bind to loopback
and nginx proxies `/world/<instance-id>/` to them through the generated map.
Do not expose the internal world port range (`10000–10999`) publicly.

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
- `cutscene-catalog` at `/cutscene-catalog`: `admin` or `game-master`; reviews
  every cutscene in the loaded world (including hidden and gated scenes), edits
  placeholder overrides, and plays local-only previews.
- `asset-bakery` at `/asset-bakery`: `admin`; loads every `bake.json` available
  to the server, previews baked PNG/GLB outputs, edits bake parameters
  (prompt, seed, sizes, faces, simplify), and reruns single tasks or batches
  through `tools/bake_assets.py`. Image tasks also offer background removal,
  resize, and trim postprocessing.

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
python tools/bake_assets.py data/phone/bake.json --progress
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

The admin Asset Bakery UI (`TRSERVER_FEATURES=asset-bakery`, `/asset-bakery`)
exposes the same workflow in the browser: pick a file, edit task prompts and
args, save or reseed the JSON, then queue a background bake and watch its log.
Bake jobs run `tools/bake_assets.py` in-process order; image outputs can also
be postprocessed (background removal, resize, trim) before rebaking.

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
