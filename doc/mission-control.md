# Tinyrooms — Mission Control

Status: implemented optional player-entry and operations server. Related docs:
[architecture.md](./architecture.md) (current components/protocol),
[db.md](./db.md) (profile and world schemas),
[milestone-3.md](./milestone-3.md) (powers, world editor, cross-world travel).

This document describes the implemented mission-control topology and contracts.

## 1. Overview

Mission control is a separate, optional server that lets an operator manage a
fleet of Tinyrooms world servers and the shared user/profile database from one
web UI. It also serves public player login and invitation-gated account creation
at `/`; operator administration is at `/mission-control`.

The operator UI has four sections:

| Section | Purpose |
| --- | --- |
| **Server Manager** | List running world servers with runtime stats, loaded world, and online users; start new instances against a chosen server version, world definition, and optional worldstate DB; drill into one server to view its log and send admin commands. |
| **Package Manager** | Inventory installed server versions (with running-instance counts and deletion of unused versions) and the shared world definitions, cardsets, and propsets installed outside any single version. |
| **Server Info** | Show the host the MC process runs on: CPU, memory, process, and filesystem metrics, plus storage used by the Tinyrooms install broken down by top-level directory. |
| **User Manager** | Query and modify accounts and related profile tables in the shared profile database; force running servers to resync user profile data. |

Player entry is public in the deployed topology. The operations UI and API are
protected by a separate operator passphrase/session; they are not a replacement
for the in-world `\admin` console or a sandbox for untrusted code.

### 1.1 Enabling it

- The mission-control server requires the feature flag:
  `TRSERVER_FEATURES=mission-control`.
- A world server participates in mission control only when
  `TRSERVER_MC_ENDPOINT` is set (see §3). Setting it does not require the
  `mission-control` flag on the world server.
- With the flag off, the mission-control routes and static UI are not mounted
  (404 / disabled), matching how `dev_sample_activity` gates optional behavior.

## 2. Terminology and topology

| Term | Meaning |
| --- | --- |
| **MC server** | The mission-control process (`run.py` when `TRSERVER_FEATURES` includes `mission-control`), serving the UI and the fleet API. |
| **World server** | An ordinary Tinyrooms process (`run.py` / `server/app.py`) serving one world and one worldstate DB. |
| **Instance** | One managed world-server process, whether spawned by MC or self-registered. |
| **Package** | An installable content bundle: a world definition, a cardset, or a propset. |
| **Template worldstate** | An optional existing `.sqlite3` file selected when starting an instance; if omitted, the server creates a fresh worldstate DB on start. |

Communication is bidirectional but every connection is initiated by a process
that is easy to reach:

```
browser
  |  HTTPS https://hostname/ (player entry + /api/entry/*)
  |  HTTPS https://hostname/mission-control (operator UI + /api/mission-control/*)
  v
nginx :443 -- fixed root proxy, no per-world routes
  v
MC server (FastAPI, HTTPS on loopback in deployment)
  |  spawns + supervises (same host)      <-- Server Manager start/stop/restart
  |  REST admin calls  ----------------->  world server /api/mc/*
  ^
  |  register / heartbeat / stats / logs
  |  (world server -> MC, outbound when TRSERVER_MC_ENDPOINT is set)
world server(s)  -- also self-register when started outside MC

browser -- direct HTTPS https://hostname:<world-port>/ --> world server
MC + participating worlds --> shared users/profiles.sqlite3
each world --> its own worldstate.sqlite3
```

- **MC → world**: REST calls for stats, log tail, admin command dispatch,
  lifecycle (stop/restart), and resync. Authenticated with the shared token.
- **World → MC**: outbound registration on startup and periodic heartbeat/stats
  pushes. Authenticated with the shared token.
- MC treats spawned children and externally started self-registered servers
  identically; only the lifecycle controls differ (MC can stop/restart a child
  it owns; external instances expose a cooperative restart/shutdown endpoint).

## 3. Configuration

### 3.1 Mission-control process

| Variable | Required? | Default | Purpose |
| --- | --- | --- | --- |
| `TRSERVER_FEATURES` | Yes | — | Must include `mission-control`. |
| `TRSERVER_MC_PASSPHRASE` | Yes | — | Operator login passphrase for the UI. |
| `TRSERVER_MC_TOKEN` | Yes | — | Shared secret for the MC ↔ world channel. |
| `TRSERVER_MC_HOST` | No | `127.0.0.1` | Listener address. |
| `TRSERVER_MC_PORT` | No | `8001` | Listener port. |
| `TRSERVER_MC_USERS_PATH` | No | `users` | Profile DB directory to manage (`profiles.sqlite3` inside it). |
| `TRSERVER_MC_INSTANCES_PATH` | No | `.local/mc-instances` | Per-instance runtime dirs for MC-spawned servers. |
| `TRSERVER_MC_VERSIONS_PATH` | No | `.local/mc-versions` | Directory of additional installed server checkouts to inventory. |
| `TRSERVER_MC_CONTENT_PATH` | No | parent of `TRSERVER_MC_VERSIONS_PATH` | Deploy content root holding shared `worlds/`, `cardsets/`, and `propsets/` plus `releases/`. |
| `TRSERVER_MC_INSTALL_PATH` | No | auto-detected | Directory whose storage the Server Info tab measures. Defaults to the deploy content root in a production deploy, otherwise the running checkout. |
| `TRSERVER_MC_CA_FILE` | No | — | PEM CA bundle used to verify world-server TLS. |
| `TRSERVER_MC_INSECURE_TLS` | No | `0` | Dev-only: skip world-server cert verification. |
| `TRSERVER_MC_HEARTBEAT_SECONDS` | No | `5` | Expected heartbeat interval; used for staleness. |
| `TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE` | No | random per config load | Invitation for player creation; also passed to spawned worlds as `TRSERVER_NEW_ACCOUNT_PASSPHRASE`. Set it explicitly for a stable invitation. |
| `TRSERVER_MC_BASE_PATH` | No | empty | Optional URL prefix; deployment uses an empty prefix. |
| `TRSERVER_MC_PUBLIC_ORIGIN` | No | — | Comma-separated extra allowed browser origins; the first determines the advertised player-entry origin. |
| `TRSERVER_MC_KEEPALIVE` | No | — | Keepalive script rerun by Reboot; set by deployment. |
| `TRSERVER_MC_INSTANCE_HOST` | No | `127.0.0.1` | Default bind address for newly spawned worlds; deployment sets `0.0.0.0`. |
| `TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME` | No | entry-origin hostname | Hostname advertised for direct world URLs, without port/path. `TRSERVER_MC_INSTANCE_PUBLIC_HOST` is the supported alias used by deployment. |
| `TRSERVER_MC_INSTANCE_PORT_MIN` | No | `5000` | Inclusive minimum allocated/explicit instance port; deployment sets `10000`. |
| `TRSERVER_MC_INSTANCE_PORT_MAX` | No | `5999` | Inclusive maximum instance port; deployment sets `10999`. |
| `TRSERVER_MC_INSTANCE_CERTFILE` | No | — | TLS certificate passed to spawned `run.py`; must be paired with the key setting and name an existing file. |
| `TRSERVER_MC_INSTANCE_KEYFILE` | No | — | TLS key paired with the certificate; deployment reuses nginx's certificate/key files. |

MC serves HTTPS with the existing self-signed cert helper (`run.py`), reusing
`.local/cert.pem` / `key.pem` unless `--certfile/--keyfile` are supplied.

### 3.2 World server (mission-control client)

| Variable | Required? | Default | Purpose |
| --- | --- | --- | --- |
| `TRSERVER_MC_ENDPOINT` | No | — | `host:port` of the MC server. When set, the world server registers and heartbeats. |
| `TRSERVER_MC_TOKEN` | Yes* | — | Shared secret; required when `TRSERVER_MC_ENDPOINT` is set. |
| `TRSERVER_MC_NAME` | No | derived | Display name for this instance (defaults to `world_id@host:port`). |
| `TRSERVER_MC_INSTANCE_ID` | No | — | Stable instance identity for registration, health/readiness, and remembered destinations; MC supplies it to spawned children. External player destinations need a configured stable identity. |
| `TRSERVER_CLIENT_URL` | No | endpoint + base path at registration | Advertised browser URL, separate from the management endpoint; player entry requires HTTPS and the same hostname as MC entry. |
| `TRSERVER_ENTRY_URL` | No | — | Player-entry URL for world root redirects; MC supplies its public origin to children. |
| `TRSERVER_SHARED_CONTENT_PATH` | No | — | Deploy content root; its `cardsets/` and `propsets/` are layered over the checkout's bundled content (shared definitions win on id collisions). |
| `TRSERVER_MC_CA_FILE` | No | — | CA bundle for verifying the MC server cert. |
| `TRSERVER_MC_INSECURE_TLS` | No | `0` | Dev-only: skip MC cert verification. |

\* Missing token with an endpoint set is a configuration error.

`server/config.py` recognizes the mission-control feature aliases.

## 4. Components and file layout

First-party components (each file under the 1200-line rule):

| Path | Responsibility |
| --- | --- |
| `run.py` | Single HTTPS launcher; selects the MC server when `TRSERVER_FEATURES` includes `mission-control` (cert reuse, uvicorn bootstrap, bounded shutdown). |
| `server/mission_control/config.py` | MC env parsing/validation (`MCConfig`). |
| `server/mission_control/app.py` | FastAPI assembly: UI routes, UI API, auth middleware, static serving. |
| `server/mission_control/entry.py` | Shared player authentication, exact-instance resolve, and persisted new-account default. |
| `server/mission_control/nginx_template.py` | Fixed MC root-proxy template used by `tools/deploy.py`, not runtime nginx management. |
| `server/mission_control/registry.py` | In-memory instance registry, heartbeat tracking, staleness eviction. |
| `server/mission_control/supervisor.py` | Spawn/stop/restart child world servers, capture stdout/stderr. |
| `server/mission_control/packages.py` | Content/version inventory, world selection, and unused-version deletion. |
| `server/mission_control/users.py` | Read/write operations over the profile DB via existing repositories. |
| `server/mission_control/audit.py` | In-memory audit ring for privileged MC actions. |
| `server/mc_client.py` | World-side outbound client: register, heartbeat, stats. |
| `server/mc_api.py` | World-side `/api/mc/*` admin endpoints. |
| `mission-control/` | Static operator UI (`index.html`) and public player entry (`entry.html`, `js/entry.js`), plus `css/`, `js/` (no build step). |

Reused as-is: `server/security.py` (hashing, sessions, CSRF, origin checks,
rate limiting), `server/profiles.py` + `server/state/migrations.py`
(`DatabaseHub`, `ProfileRepository`), `server/content/` loaders for package
validation, and the `run.py` cert/shutdown helpers.

Outbound HTTP uses `httpx` (async).

### 4.1 Runtime state and persisted launch settings

MC has no separate database. Live registration/metrics, package index, audit,
and operator sessions are in memory. Spawned stable identities and launch
settings persist in `<TRSERVER_MC_INSTANCES_PATH>/<instance-id>/instance.json`.
Startup restores those records as unreachable until registration; merely
restoring an identity does not spawn a process. `resume.json` records children
to respawn after Reboot, and `entry.json` persists the new-account default.
External records are rebuilt through registration. Player accounts/sessions
remain in the shared profile database.

## 5. Mission-control UI

Served at `<MC host:port>/mission-control`. Static vanilla ES modules, no build
step, reusing the project's design tokens where practical; layout may be denser
and more utilitarian than the game client.

### 5.1 Authentication

- `/mission-control` serves the operator login shell; protected
  `/api/mission-control/*` requests return 401 without an operator session.
- `POST /api/mission-control/auth/login` takes `{passphrase}` plus the `Origin`
  header; a correct passphrase (constant-time compare against
  `TRSERVER_MC_PASSPHRASE`) issues an MC session cookie and CSRF cookie using
  the existing `server/security.py` primitives. MC sessions are independent of
  any world account.
- All authenticated POSTs require `Origin` + matching `X-CSRF-Token`.
- `POST .../auth/logout` clears cookies.
- Failed logins are rate-limited by source address.

### 5.2 Tabbed shell

A single page with four tabs (Server Manager, Package Manager, Server Info, User Manager),
plus a persistent header showing the logged-in operator, MC version, and a
disconnect/error banner when world servers are unreachable.

### 5.3 Server Manager

**List view** — one row per known instance:

| Field | Notes |
| --- | --- |
| Name / instance id | Stable id; display name from `TRSERVER_MC_NAME` or spawned config. |
| Endpoint | `https://host:port`. |
| Client URL | Advertised direct browser URL; may differ from the management endpoint. |
| Status | `starting`, `running`, `unreachable`, `stopped`, `external`. |
| World | World id and label loaded by that server. |
| Version | Server build + protocol version. |
| Uptime | Since process/registration start. |
| Users online | Count of live sessions/connections. |
| Source | `spawned` or `external`. |
| Last heartbeat | Age; stale past threshold marks `unreachable`. |

**Start instance form** — fields:

- Server version (required): pick an installed version (defaults to the running
  build). The child runs that checkout's `run.py`.
- World definition (required): pick from shared worlds plus the selected
  version's bundled worlds.
- Worldstate DB (optional): pick an existing `.sqlite3` file, or leave blank
  for a fresh DB created on start.
- Users path (optional): defaults to `TRSERVER_MC_USERS_PATH`.
- Name, host, port (host defaults to `TRSERVER_MC_INSTANCE_HOST`).
- Feature flags / admins (optional passthrough).

On submit, MC allocates an instance directory under
`TRSERVER_MC_INSTANCES_PATH/<instance-id>/`, spawns `run.py` with the derived
env (`TRSERVER_WORLD_PATH`, `TRSERVER_WORLDSTATE_PATH`, `TRSERVER_USERS_PATH`,
`TRSERVER_MC_ENDPOINT`, `TRSERVER_MC_TOKEN`, `TRSERVER_MC_NAME`,
`TRSERVER_MC_INSTANCE_ID`, `TRSERVER_CLIENT_URL`, `TRSERVER_ENTRY_URL`, port/host),
persists `instance.json`, and tracks the child handle.

**Drilldown view** for a selected instance:

- Runtime stats: uptime, online user list (id/username/room), room count,
  world/card counts, DB schema versions.
- **Log panel**: tail of captured stdout/stderr (ring buffer, bounded, e.g.
  1000 lines), with auto-refresh and pause.
- **Admin console**: a text input that dispatches an admin command to the
  world server and displays the result. Commands are validated server-side
  against the world's admin capability set; MC does not invent new in-world
  commands.
- **Lifecycle controls**: Start / Stop / Restart (spawned instances); for
  external instances, cooperative Shutdown/Restart via the world API. Restarting
  a spawned instance preserves its instance id and saved launch settings,
  including host, port, base path, client URL, and version selection.
- **Rename** (spawned only): changes the display name, persists the identity
  file, and restarts a non-stopped child. It preserves the id, direct URL, and
  any legacy base path. External instances cannot be renamed through this action.
- **Delete**: stops a spawned child and removes its registry record, identity
  file, and resume entry; worldstate and other data are left on disk. External
  instances are cooperatively shut down and dropped.
- **Make default**: validates and persists the destination for new accounts
  (§2.1); the list and drilldown show a Default badge.
- **Resync** button (see §5.5).
- **Reboot**: stops every running spawned instance, writes their launch configs
  to `TRSERVER_MC_INSTANCES_PATH/resume.json`, and shuts down the MC process. The
  keepalive script (per-minute cron and immediate trigger) restarts MC, which
  respawns the recorded instances on startup. External instances are not resumed.

There is no **Update nginx config** action. Start/stop/restart/rename/delete
operate independently of nginx.

### 5.4 Package Manager

**Server versions** — the running build plus any additional checkouts found
under `TRSERVER_MC_VERSIONS_PATH` (skipping the `latest` symlink and any
checkout that resolves to the running build). Each row shows its id (directory
name), build label, protocol version, git commit/tag, the number of currently
running instances on that build (plus the registered count when it differs),
and path. The build label is read from each checkout's own `version.json`.

**Delete version** — removes an unused version directory and its
`releases/tinyrooms-<id>.tar.gz` artifact. The running version and any version
with a registered instance (running, starting, unreachable, or stopped) are
protected; the confirmation dialog states the deletion explicitly. Audited.

**Shared content** — the world definitions, cardsets, and propsets installed
**outside any single server version**, under the deploy content root (§8.4).
Each row shows id, manifest version (when present), validation status
(`ok`/`error` with messages), and source path. This view is read-only: deploy
and content management happen on disk via `tools/deploy.py`, not the UI.

**Start-instance worlds** — the Server Manager's version picker selects a code
checkout; its world picker lists shared worlds plus that version's bundled
worlds (§5.3).

### 5.5 User Manager

Connects directly to the configured profile DB (§4, §8.2) and provides:

- **Search/list** accounts by username (case-insensitive) or id, with level,
  kudos, bops, sticker, created/last-seen, and granted powers.
- **Detail view** across related tables: `accounts`, `sessions`,
  `profile_card_stacks` (inventory), `user_profiles`, `reward_ledger`,
  `pack_purchases`, `task_progress`, `memories`, and `audit_log`.
- **Edit** supported fields: level, kudos, bops, shared energy, sticker,
  `initial_sticker_complete`, mute state, and powers grant/revoke. Every change
  is written through `ProfileRepository`/`PowersService`-equivalent logic and
  recorded in the MC audit log (and, where a world context exists, the world
  audit table).
- **Resync**: choose one running instance or "all instances" and force a
  profile reload (see §11.5). Shows per-instance success/failure.

### 5.6 Server Info

Describes the host the MC process runs on. Read-only and operator-only; no
secrets (MC token/passphrase) are ever included.

- **Host**: hostname, OS/release/machine, CPU model and logical count, Python
  version, host uptime, and load average.
- **CPU**: system busy percent and MC process CPU percent, sampled over a short
  (~150 ms) window in a worker thread so the event loop is not blocked.
- **Memory**: total/used/available and swap (host-wide).
- **MC process**: pid, uptime, resident/virtual memory, thread count.
- **Disk**: total/used/free and percent for the filesystem holding the install
  root.
- **Configuration**: MC version, protocol, profile/world schema versions,
  listen address, feature flags, keepalive configuration, and the
  repo/content/install/versions/releases/users paths.
- **Install storage**: recursive size of each top-level entry of the install
  root (`TRSERVER_MC_INSTALL_PATH`, auto-detected — see §3.1), shown as a size
  and share bar. The scan runs in a worker thread, does not follow symlinks, is
  cached for 60 s, and can be forced with `?refresh=1`.

**Linux-first**: system CPU, memory, swap, host uptime, and load average are
read from `/proc` and `os.getloadavg` and therefore only appear on Linux hosts;
other platforms show an em dash. Host, process, disk, and storage figures work
everywhere. The UI auto-refreshes metrics every 5 s (toggleable) and rescans
storage on demand.

## 6. World-server mission-control API (`server/mc_api.py`)

Mounted only when `TRSERVER_MC_ENDPOINT` is set. All endpoints require the
shared token via `X-MC-Token` (constant-time compare); mismatches return 403
and are logged. These endpoints are never available to game clients.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/mc/stats` | — | `{ok, uptime, users[], rooms, world, version, schema{profile,world}, counters}` |
| `GET` | `/api/mc/logs?limit=` | — | `{ok, lines[]}` (server-local recent log ring) |
| `POST` | `/api/mc/command` | `{command, request_id?}` | `{ok, result}` or `{ok:false, code, message}` |
| `POST` | `/api/mc/restart` | No body | `{ok}` (cooperative restart) |
| `POST` | `/api/mc/shutdown` | No body | `{ok}` (cooperative stop) |
| `POST` | `/api/mc/resync` | `{scope}` | `{ok, refreshed, notified_clients}` |

- `capabilities` declares which admin commands the instance accepts; MC's
  console uses it to validate input before sending.
- `POST /api/mc/command` routes through the existing command/admin dispatch
  pipeline (`server/commands/admin.py`) so authorization, blocking (`\r`,
  `\k`), and audit behavior are identical to the in-game console. A command
  uses the first existing account in the world's `TRSERVER_ADMINS`, sorted by
  username. If no configured admin account exists, it returns `admin_unavailable`.
  It never bypasses `PowersService` or accepts a caller-selected execution account.
- Registration and heartbeat are served by MC, not by the world API (§6.1).

### 6.1 World-side outbound client (`server/mc_client.py`)

- On startup: POST `/api/mc/register`; on failure, log and retry with
  exponential backoff (bounded).
- Periodically POST `/api/mc/heartbeat` every `heartbeat_seconds`.
- If MC is unreachable, the world server keeps serving players normally; only
  MC management is degraded.
- On graceful shutdown: best-effort deregister (or let MC evict by staleness).

MC's token-authenticated fleet endpoints are `POST /api/mc/register`,
`POST /api/mc/heartbeat`, and `POST /api/mc/deregister`. Registration includes
`instance_id`, `instance_name`, management `endpoint`, public `client_url`,
`base_path`, version/protocol, and `world` identity/entry-room data.

## 7. Mission-control UI API

Mounted on the MC server, gated by the `mission-control` feature. Operator
login validates the passphrase; protected operations require an MC session.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/mission-control/auth/login` | Passphrase login. |
| `POST` | `/api/mission-control/auth/logout` | End MC session. |
| `GET` | `/api/mission-control/session` | Current operator/session. |
| `GET` | `/api/mission-control/servers` | List instances + summary stats. |
| `POST` | `/api/mission-control/servers` | Start a new instance. |
| `GET` | `/api/mission-control/servers/{id}` | Instance detail. |
| `POST` | `/api/mission-control/servers/{id}/stop` | Stop instance. |
| `POST` | `/api/mission-control/servers/{id}/restart` | Restart instance in place. |
| `POST` | `/api/mission-control/servers/{id}/rename` | Rename a spawned instance, preserving its URL. |
| `DELETE` | `/api/mission-control/servers/{id}` | Stop/remove instance. |
| `POST` | `/api/mission-control/instances/{id}/default` | Validate and persist the new-account default. |
| `POST` | `/api/mission-control/reboot` | Stop spawned instances and restart MC via keepalive. |
| `GET` | `/api/mission-control/servers/{id}/logs` | Log tail. |
| `POST` | `/api/mission-control/servers/{id}/command` | Send admin command. |
| `POST` | `/api/mission-control/servers/{id}/resync` | Resync one instance. |
| `POST` | `/api/mission-control/resync` | Resync all instances. |
| `GET` | `/api/mission-control/packages` | Shared-content + server-version inventory. |
| `GET` | `/api/mission-control/worlds?version=` | Worlds available to a server version. |
| `DELETE` | `/api/mission-control/versions/{id}` | Delete an unused server version. |
| `GET` | `/api/mission-control/server` | Host/CPU/memory/process/disk/config snapshot. |
| `GET` | `/api/mission-control/server/storage?refresh=` | Install storage breakdown by top-level directory. |
| `GET` | `/api/mission-control/users` | Search/list accounts. |
| `GET` | `/api/mission-control/users/{id}` | Account detail + related rows. |
| `PATCH` | `/api/mission-control/users/{id}` | Edit supported fields. |
| `GET` | `/api/mission-control/audit` | Recent MC audit entries. |

Authenticated non-GET operations require `Origin` + `X-CSRF-Token`; login
requires Origin and the passphrase. Responses use a consistent
`{ok, ...}` / `{ok:false, code, message}` envelope.

### 7.1 Public player-entry API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/entry/session` | Report shared player session and CSRF token when logged in. |
| `POST` | `/api/entry/login` | Verify username/password and issue shared player cookies. |
| `POST` | `/api/entry/create` | Verify invitation, validate default, create account and save its destination. |
| `POST` | `/api/entry/logout` | Revoke player session and clear cookies. |
| `GET` | `/api/entry/resolve` | Resolve the authenticated player's saved destination (§2.1). |

Login/create require a valid Origin and are rate-limited. Logout requires Origin
and matching session/header/cookie CSRF tokens.

## 8. Data model and storage

### 8.1 Instance registry (in memory)

```
InstanceRecord {
  instance_id, name, endpoint, client_url, base_path, entry_room_id, token_source,
  source: spawned | external,
  status, world_id, world_label, version, protocol_version,
  started_at, last_heartbeat_at, uptime_seconds,
  users_online, stats_cache,
  process_handle?, instance_dir?, log_buffer
}
```

- `log_buffer` is a bounded ring (per instance) fed from child stdout/stderr
  for spawned instances, or from periodic `/api/mc/logs` polling for external
  ones.
- Instances with no heartbeat past `stale_after` (e.g. 3× heartbeat interval)
  become `unreachable`; spawned children whose process exits become `stopped`.

### 8.2 Profile database access

- MC opens `<TRSERVER_MC_USERS_PATH>/profiles.sqlite3` via
  `DatabaseHub`/`ProfileRepository`, running `ensure_profile_database` on
  startup and rejecting newer schema versions exactly as the world server does.
- **No schema changes are required** for mission control. MC reads/writes the
  existing `accounts`, `sessions`, `profile_card_stacks`, `user_profiles`,
  `reward_ledger`, `pack_purchases`, `task_progress`, `memories`, and
  `audit_log` tables.
- MC must tolerate the world server holding the DB open concurrently: WAL mode
  and `BEGIN IMMEDIATE` transactions are already used; MC writes use the same
  repository transaction patterns and keep transactions short.

### 8.3 Deployment and upgrades

`tools/deploy.py` installs a static nginx site: TCP 80 redirects to HTTPS;
TCP 443 proxies the root and all application paths to the loopback MC port.
Player entry is `https://<hostname>/`, operator administration is
`https://<hostname>/mission-control`, and worlds are
`https://<hostname>:<world-port>/`.

Deployment writes these direct-world settings to `<rootdir>/admin.env`:

- `TRSERVER_MC_INSTANCE_HOST=0.0.0.0` (worlds bind on all IPv4 interfaces).
- `TRSERVER_MC_INSTANCE_PUBLIC_HOST=<public hostname>` (supported alias for
  `TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME`).
- `TRSERVER_MC_INSTANCE_PORT_MIN=10000` and
  `TRSERVER_MC_INSTANCE_PORT_MAX=10999` (inclusive).
- `TRSERVER_MC_INSTANCE_CERTFILE=<rootdir>/nginx/certs/server.crt` and
  `TRSERVER_MC_INSTANCE_KEYFILE=<rootdir>/nginx/certs/server.key` (reuse the
  nginx TLS files for child worlds).
- Empty `TRSERVER_MC_BASE_PATH`, `TRSERVER_MC_PUBLIC_ORIGIN=https://<hostname>`,
  shared users/content paths, and the keepalive path.

### 8.4 Content roots

Inside a checkout, content lives at `<checkout>/worlds/`, `<checkout>/data/cardsets/`,
and `<checkout>/data/propsets/`; each deployed server version bundles its own
copy. The deploy content root (`TRSERVER_MC_CONTENT_PATH` for MC,
`TRSERVER_SHARED_CONTENT_PATH` for world servers) additionally holds content
installed **outside** any single version:

| Kind | Shared root | Detection |
| --- | --- | --- |
| World | `<root>/worlds/<id>/` | `world.yaml` present. |
| Cardset | `<root>/cardsets/<id>/` | `cards.yaml` present (optional `pack.yaml`). |
| Propset | `<root>/propsets/<id>/` | `props.yaml` present. |

`tools/deploy.py` creates these directories and points MC at the deploy root;
content is placed there on disk, not uploaded through the UI.

At runtime the world loader layers shared cardsets and propsets over the
checkout's bundled ones, with **shared definitions winning on id collisions**
(duplicate ids *within* one root remain an error). World-local `props/` and
card definitions are validated as before. A world definition may itself be
shared or bundled; the Server Manager lists shared worlds plus the chosen
version's bundled worlds and resolves the selected id accordingly.

### 8.5 Audit (in memory)

MC records `{at, actor, action, target, result, detail}` for login attempts,
instance start/stop/restart/command, resync, package install/enable/delete,
and user edits. Bounded ring; surfaced in the UI. Lost on MC restart by design.

## 9. Security model

- **Trust boundary**: MC defaults to loopback behind nginx in deployment.
  Player entry is public; privileged fleet/user operations require operator auth.
- **UI auth**: separate MC passphrase, hashed/constant-time compared; MC
  session + CSRF cookies; `Origin` validation on state-changing requests.
- **Channel auth**: shared `TRSERVER_MC_TOKEN` on every MC↔world request,
  compared with `hmac.compare_digest`; missing/invalid token → 403 + audit.
- **TLS**: MC and world servers use the existing self-signed cert mechanism.
  Peers verify against `*_CA_FILE` when provided; `*_INSECURE_TLS=1` is an
  explicit dev-only escape hatch and must log a warning at startup.
- **Admin commands**: dispatched through the existing command/admin pipeline;
  the selected bootstrap-admin account must satisfy the world's power checks. MC cannot grant itself
  in-world powers through this path.
- **Version deletion**: restricted to installed version directories under
  `TRSERVER_MC_VERSIONS_PATH`; refuses the running version, path escapes, and
  versions with any registered instance; deletes the directory and the matching
  release artifact. Audited.
- **Shared content**: operator-installed trusted code (including behavior
  scripts); content inventory and privileged operations require operator auth.
- **User edits**: validated against the same field constraints the game
  enforces; every change audited.

## 10. Feature gating and degradation

- MC process without the `mission-control` feature fails configuration with a
  clear error (feature flag is required).
- World server with `TRSERVER_MC_ENDPOINT` but no `TRSERVER_MC_TOKEN` fails
  configuration.
- World server keeps serving players when MC is down or the token is rejected;
  MC management degrades, gameplay does not.
- MC UI shows unreachable instances distinctly and never blocks the list view
  on a slow/dead instance (per-instance timeouts on stats/log calls).

## 11. Key flows

1. **MC startup**: load MC config, ensure profile DB, scan content roots to
   build the package index, mount UI + API, begin accepting registrations.
2. **World server startup (self-registered)**: read `TRSERVER_MC_ENDPOINT`,
   register, then heartbeat on an interval; MC upserts the instance record.
3. **MC-spawned instance**: operator submits the start form → MC allocates an
   instance dir and free port → spawns `run.py` with derived env → child
   registers → MC marks it `running` and begins capturing logs.
4. **Admin command**: operator sends text in the drilldown console → MC
   validates against the instance `capabilities` → `POST /api/mc/command` →
   world dispatches through the admin pipeline → result returned and audited.
5. **Resync**: operator triggers resync for one/all instances → MC calls
   `POST /api/mc/resync` → world invalidates any cached profile state, bumps a
   profile revision, and notifies live clients to refresh → MC reports
   refreshed instance count and notified clients. (Today the world reads
   profile data per request; this endpoint defines the forward-compatible
   contract and the live-refresh behavior.)
6. **Version delete / content inventory**: operator deletes an unused version
   → MC re-checks it is not running and has no registered instance → removes the
   checkout and its release artifact and audits the action. Shared content is
   scanned from the deploy content root and shown read-only with validation
   status.
7. **Stale eviction**: a spawned child exits or an external instance stops
   heartbeating → MC transitions the record to `stopped`/`unreachable` and
   surfaces it in the UI.

## 12. Testing strategy

Follow existing harness patterns.

- **Unit (`unittest`)**: MC config validation (feature required, token/passphrase
  required); MC auth + CSRF + origin; registry upsert/staleness/eviction;
  package manifest parsing, traversal rejection, size limits, and
  validate-before-write; user repository read/write against a temp profile DB;
  world-side `mc_client` register/heartbeat retry/backoff with a mocked HTTP
  transport; `/api/mc/*` token enforcement via `TestClient`.
- **Integration**: start an MC `TestClient` app plus a world `TestClient` app
  configured with an MC endpoint (in-process or loopback subprocess); assert
  registration, heartbeat, stats, command dispatch, and resync round-trips.
  Reuse `tests/test_milestone1.py:RuntimeTestCase` and
  `tests/common.py:ServiceTestCase` isolation (temp users/worldstate).
- **Browser (Playwright)**: MC login, tab navigation, server list rendering,
  start-form validation, package inventory, and user search/edit using the
  existing per-test server fixture pattern. Add visual snapshots only if the
  design review wants them.
- Keep every new file under 1200 lines (enforced by
  `tests/test_ui_presentation.py`).

## 13. Original delivery phases

| Phase | Scope |
| --- | --- |
| **A** | `mission-control` feature flag + `KNOWN_FEATURES`; `MCConfig`; `run.py` mode selection; MC app skeleton, passphrase auth, static UI shell with three tabs. |
| **B** | World-side `mc_client.py` + `mc_api.py` (register/heartbeat/stats/logs/command); MC registry + heartbeat/staleness; instance list view. |
| **C** | Server Manager drilldown: log capture/polling, admin console, start/stop/restart, spawn supervisor, optional worldstate selection. |
| **D** | Package Manager: server-version inventory with per-version instance counts and unused-version deletion; read-only shared world/cardset/propset inventory; shared-over-bundled content loading. |
| **E** | User Manager: direct profile DB access, search/detail/edit, audit view, resync endpoint + UI. |
| **F** | Full test coverage, README/config documentation, security review, polish. |

## 14. Open questions and future work

- **Remote registry**: fetching package/version indexes from a remote source
  (deferred; current inventory is local, with deployment/content managed on disk).
- **MC persistence**: a durable MC DB for audit/live registry across restarts;
  currently those are in memory, while identity, launch, resume, and default
  settings already persist as JSON files (§4.1).
- **Multi-host orchestration**: managing instances on other machines,
  containers, or process supervisors beyond local children.
- **Stronger operator identity**: per-operator accounts/roles instead of a
  single shared passphrase.
- **Log streaming**: server-sent events or WebSocket streaming instead of
  polling for live log tails.
