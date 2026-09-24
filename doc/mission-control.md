# Tinyrooms — Mission Control

Status: design specification for a new optional server. Related docs:
[architecture.md](./architecture.md) (current components/protocol),
[db.md](./db.md) (profile and world schemas),
[milestone-3.md](./milestone-3.md) (powers, world editor, cross-world travel).

This document specifies **what** mission control must do and the contracts
between components. Fine-grained implementation choices (module internals, exact
SQL, CSS) are intentionally left to the build agent.

## 1. Overview

Mission control is a separate, optional server that lets an operator manage a
fleet of Tinyrooms world servers and the shared user/profile database from one
web UI.

It has three sections:

| Section | Purpose |
| --- | --- |
| **Server Manager** | List running world servers with runtime stats, loaded world, and online users; start new instances against a chosen world definition and optional worldstate DB; drill into one server to view its log and send admin commands. |
| **Package Manager** | Inventory available Tinyrooms server versions, world definitions, cardsets, and propsets; upload/install, enable/disable, and delete content packages. |
| **User Manager** | Query and modify accounts and related profile tables in the shared profile database; force running servers to resync user profile data. |

Mission control is a development/operations tool. It is **not** a public
service, not a replacement for the in-world `\admin` console, and not a
sandbox for untrusted code. It runs on a trusted host/network.

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
| **MC server** | The mission-control process (`run_mission_control.py`), serving the UI and the fleet API. |
| **World server** | An ordinary Tinyrooms process (`run.py` / `server/app.py`) serving one world and one worldstate DB. |
| **Instance** | One managed world-server process, whether spawned by MC or self-registered. |
| **Package** | An installable content bundle: a world definition, a cardset, or a propset. |
| **Template worldstate** | An optional existing `.sqlite3` file selected when starting an instance; if omitted, the server creates a fresh worldstate DB on start. |

Communication is bidirectional but every connection is initiated by a process
that is easy to reach:

```
browser
  |  HTTPS /mission-control, /api/mission-control/*
  v
MC server (FastAPI, optional TLS)
  |  spawns + supervises (same host)      <-- Server Manager start/stop/restart
  |  REST admin calls  ----------------->  world server /api/mc/*
  ^
  |  register / heartbeat / stats / logs
  |  (world server -> MC, outbound when TRSERVER_MC_ENDPOINT is set)
world server(s)  -- also self-register when started outside MC
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
| `TRSERVER_MC_CA_FILE` | No | — | PEM CA bundle used to verify world-server TLS. |
| `TRSERVER_MC_INSECURE_TLS` | No | `0` | Dev-only: skip world-server cert verification. |
| `TRSERVER_MC_HEARTBEAT_SECONDS` | No | `5` | Expected heartbeat interval; used for staleness. |

MC serves HTTPS with the existing self-signed cert helper (`run.py`), reusing
`.local/cert.pem` / `key.pem` unless `--certfile/--keyfile` are supplied.

### 3.2 World server (mission-control client)

| Variable | Required? | Default | Purpose |
| --- | --- | --- | --- |
| `TRSERVER_MC_ENDPOINT` | No | — | `host:port` of the MC server. When set, the world server registers and heartbeats. |
| `TRSERVER_MC_TOKEN` | Yes* | — | Shared secret; required when `TRSERVER_MC_ENDPOINT` is set. |
| `TRSERVER_MC_NAME` | No | derived | Display name for this instance (defaults to `world_id@host:port`). |
| `TRSERVER_MC_CA_FILE` | No | — | CA bundle for verifying the MC server cert. |
| `TRSERVER_MC_INSECURE_TLS` | No | `0` | Dev-only: skip MC cert verification. |

\* Missing token with an endpoint set is a configuration error.

`KNOWN_FEATURES` in `server/config.py` gains `"mission-control"` (and keeps the
existing underscore/hyphen normalization).

## 4. Components and file layout

New first-party code (each file under the 1200-line rule):

| Path | Responsibility |
| --- | --- |
| `run_mission_control.py` | HTTPS launcher for the MC server (cert reuse, uvicorn bootstrap, bounded shutdown). |
| `server/mission_control/config.py` | MC env parsing/validation (`MCConfig`). |
| `server/mission_control/app.py` | FastAPI assembly: UI routes, UI API, auth middleware, static serving. |
| `server/mission_control/registry.py` | In-memory instance registry, heartbeat tracking, staleness eviction. |
| `server/mission_control/supervisor.py` | Spawn/stop/restart child world servers, capture stdout/stderr. |
| `server/mission_control/packages.py` | Content-root scanning, package index, upload validation/install. |
| `server/mission_control/users.py` | Read/write operations over the profile DB via existing repositories. |
| `server/mission_control/audit.py` | In-memory audit ring for privileged MC actions. |
| `server/mc_client.py` | World-side outbound client: register, heartbeat, stats. |
| `server/mc_api.py` | World-side `/api/mc/*` admin endpoints. |
| `mission-control/` | Static UI: `index.html`, `css/`, `js/` (no build step). |

Reused as-is: `server/security.py` (hashing, sessions, CSRF, origin checks,
rate limiting), `server/profiles.py` + `server/state/migrations.py`
(`DatabaseHub`, `ProfileRepository`), `server/content/` loaders for package
validation, and the `run.py` cert/shutdown helpers.

Outbound HTTP uses `httpx` (async). Add it to `requirements.txt`; it is already
a dev dependency for `TestClient`.

### 4.1 MC state is in memory

Per the design decision, MC keeps no database of its own. The instance
registry, package index, and audit log live in process memory and are rebuilt
on startup (registry from registration/heartbeat; package index from a content
scan). MC restarting drops live instance records until servers re-heartbeat and
requires no migrations. This is acceptable because MC is an operations tool.

## 5. Mission-control UI

Served at `<MC host:port>/mission-control`. Static vanilla ES modules, no build
step, reusing the project's design tokens where practical; layout may be denser
and more utilitarian than the game client.

### 5.1 Authentication

- Unauthenticated requests to `/mission-control` or
  `/api/mission-control/*` redirect/401 to a login screen.
- `POST /api/mission-control/auth/login` takes `{passphrase}` plus the `Origin`
  header; a correct passphrase (constant-time compare against
  `TRSERVER_MC_PASSPHRASE`) issues an MC session cookie and CSRF cookie using
  the existing `server/security.py` primitives. MC sessions are independent of
  any world account.
- All authenticated POSTs require `Origin` + matching `X-CSRF-Token`.
- `POST .../auth/logout` clears cookies.
- Failed logins are rate-limited by source address.

### 5.2 Tabbed shell

A single page with three tabs (Server Manager, Package Manager, User Manager),
plus a persistent header showing the logged-in operator, MC version, and a
disconnect/error banner when world servers are unreachable.

### 5.3 Server Manager

**List view** — one row per known instance:

| Field | Notes |
| --- | --- |
| Name / instance id | Stable id; display name from `TRSERVER_MC_NAME` or spawned config. |
| Endpoint | `https://host:port`. |
| Status | `starting`, `running`, `unreachable`, `stopped`, `external`. |
| World | World id and label loaded by that server. |
| Version | Server build + protocol version. |
| Uptime | Since process/registration start. |
| Users online | Count of live sessions/connections. |
| Source | `spawned` or `external`. |
| Last heartbeat | Age; stale past threshold marks `unreachable`. |

**Start instance form** — fields:

- World definition (required): pick from installed world packages.
- Worldstate DB (optional): pick an existing `.sqlite3` file, or leave blank
  for a fresh DB created on start.
- Users path (optional): defaults to `TRSERVER_MC_USERS_PATH`.
- Name, host, port (host/port default to an allocated free port on
  `127.0.0.1`).
- Feature flags / admins (optional passthrough).

On submit, MC allocates an instance directory under
`TRSERVER_MC_INSTANCES_PATH/<instance-id>/`, spawns `run.py` with the derived
env (`TRSERVER_WORLD_PATH`, `TRSERVER_WORLDSTATE_PATH`, `TRSERVER_USERS_PATH`,
`TRSERVER_MC_ENDPOINT`, `TRSERVER_MC_TOKEN`, `TRSERVER_MC_NAME`, port/host),
and tracks the child handle.

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
  external instances, cooperative Shutdown/Restart via the world API.
- **Resync** button (see §5.5).

### 5.4 Package Manager

**Inventory view** — four groups, each item showing name/id, version, source
path, and validation status (`ok`, `warning`, `error` with messages):

- **Server versions**: the running build (version file/constant, git
  commit/tag, protocol version, profile/world schema versions) plus any
  additional checkouts found under `TRSERVER_MC_VERSIONS_PATH`.
- **World definitions**: directories under `worlds/` containing `world.yaml`.
- **Cardsets**: directories under `data/cardsets/` containing `cards.yaml`.
- **Propsets**: directories under `data/propsets/` (new shared root, §8.3).

**Install/upload**: upload a zip containing a manifest that declares the
package kind and id. MC validates structure and runs the matching content
loader **before** extraction; a package that fails validation is rejected with
messages and nothing is written. On success, extract to the canonical root
(`worlds/<id>`, `data/cardsets/<id>`, or `data/propsets/<id>`).

**Manage**: enable/disable (tracked in memory for the session; disabled
packages are hidden from start/new-instance pickers) and delete (removes the
installed directory after confirmation). All actions are audited.

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

## 6. World-server mission-control API (`server/mc_api.py`)

Mounted only when `TRSERVER_MC_ENDPOINT` is set. All endpoints require the
shared token via `X-MC-Token` (constant-time compare); mismatches return 403
and are logged. These endpoints are never available to game clients.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/mc/register` | `{instance_name, endpoint, version, protocol_version, world{id,label}, started_at}` | `{ok, instance_id, heartbeat_seconds, capabilities[]}` |
| `POST` | `/api/mc/heartbeat` | `{instance_id, uptime_seconds, users_online, world_id}` | `{ok, pending_commands?}` |
| `GET` | `/api/mc/stats` | — | `{ok, uptime, users[], rooms, world, version, schema{profile,world}, counters}` |
| `GET` | `/api/mc/logs?limit=` | — | `{ok, lines[]}` (server-local recent log ring) |
| `POST` | `/api/mc/command` | `{command, actor, request_id}` | `{ok, result}` or `{ok:false, code, message}` |
| `POST` | `/api/mc/restart` | `{actor}` | `{ok}` (cooperative restart) |
| `POST` | `/api/mc/shutdown` | `{actor}` | `{ok}` (cooperative stop) |
| `POST` | `/api/mc/resync` | `{actor, scope}` | `{ok, refreshed, notified_clients}` |

- `capabilities` declares which admin commands the instance accepts; MC's
  console uses it to validate input before sending.
- `POST /api/mc/command` routes through the existing command/admin dispatch
  pipeline (`server/commands/admin.py`) so authorization, blocking (`\r`,
  `\k`), and audit behavior are identical to the in-game console. A command
  that requires an actor account uses the operator's configured MC identity
  mapped to a bootstrap-admin context; it never bypasses `PowersService`.
- Registration/heartbeat are idempotent per `instance_id`; re-registration
  after an MC restart replaces the prior record.

### 6.1 World-side outbound client (`server/mc_client.py`)

- On startup: POST `/api/mc/register`; on failure, log and retry with
  exponential backoff (bounded).
- Periodically POST `/api/mc/heartbeat` every `heartbeat_seconds`.
- If MC is unreachable, the world server keeps serving players normally; only
  MC management is degraded.
- On graceful shutdown: best-effort deregister (or let MC evict by staleness).

## 7. Mission-control UI API

Mounted on the MC server, gated by the `mission-control` feature and MC auth.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/mission-control/auth/login` | Passphrase login. |
| `POST` | `/api/mission-control/auth/logout` | End MC session. |
| `GET` | `/api/mission-control/session` | Current operator/session. |
| `GET` | `/api/mission-control/servers` | List instances + summary stats. |
| `POST` | `/api/mission-control/servers` | Start a new instance. |
| `GET` | `/api/mission-control/servers/{id}` | Instance detail. |
| `POST` | `/api/mission-control/servers/{id}/stop` | Stop instance. |
| `POST` | `/api/mission-control/servers/{id}/restart` | Restart instance. |
| `GET` | `/api/mission-control/servers/{id}/logs` | Log tail. |
| `POST` | `/api/mission-control/servers/{id}/command` | Send admin command. |
| `POST` | `/api/mission-control/servers/{id}/resync` | Resync one instance. |
| `POST` | `/api/mission-control/resync` | Resync all instances. |
| `GET` | `/api/mission-control/packages` | Package inventory. |
| `POST` | `/api/mission-control/packages` | Upload/install a package zip. |
| `POST` | `/api/mission-control/packages/{kind}/{id}/enable` | Enable/disable. |
| `DELETE` | `/api/mission-control/packages/{kind}/{id}` | Delete a package. |
| `GET` | `/api/mission-control/users` | Search/list accounts. |
| `GET` | `/api/mission-control/users/{id}` | Account detail + related rows. |
| `PATCH` | `/api/mission-control/users/{id}` | Edit supported fields. |
| `GET` | `/api/mission-control/audit` | Recent MC audit entries. |

All non-GET require `Origin` + `X-CSRF-Token`. Responses use a consistent
`{ok, ...}` / `{ok:false, code, message}` envelope.

## 8. Data model and storage

### 8.1 Instance registry (in memory)

```
InstanceRecord {
  instance_id, name, endpoint, token_source,
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

### 8.3 Content roots and packages

| Kind | Root | Detection |
| --- | --- | --- |
| World | `worlds/<id>/` | `world.yaml` present. |
| Cardset | `data/cardsets/<id>/` | `cards.yaml` present (optional `pack.yaml`). |
| Propset | `data/propsets/<id>/` | `props.yaml` present (new shared root). |

Introducing `data/propsets/` requires a loader change: the world loader must
merge shared propsets with the world-local `props/` directory (world-local
definitions win on id collisions, mirroring core/world activity merging). The
package manager inventories both shared propsets and each world's local props.

Package zip layout: a top-level manifest (`package.json` or `package.yaml`)
declaring `{kind, id, version, label}` plus the package files. Install
validates by running the appropriate loader against the extracted-to-temp copy,
then moves into the canonical root.

### 8.4 Audit (in memory)

MC records `{at, actor, action, target, result, detail}` for login attempts,
instance start/stop/restart/command, resync, package install/enable/delete,
and user edits. Bounded ring; surfaced in the UI. Lost on MC restart by design.

## 9. Security model

- **Trust boundary**: MC is an operator tool for trusted hosts/networks. It
  defaults to loopback and is not hardened for public exposure.
- **UI auth**: separate MC passphrase, hashed/constant-time compared; MC
  session + CSRF cookies; `Origin` validation on state-changing requests.
- **Channel auth**: shared `TRSERVER_MC_TOKEN` on every MC↔world request,
  compared with `hmac.compare_digest`; missing/invalid token → 403 + audit.
- **TLS**: MC and world servers use the existing self-signed cert mechanism.
  Peers verify against `*_CA_FILE` when provided; `*_INSECURE_TLS=1` is an
  explicit dev-only escape hatch and must log a warning at startup.
- **Admin commands**: dispatched through the existing command/admin pipeline;
  the MC actor must satisfy the world's power checks. MC cannot grant itself
  in-world powers through this path.
- **Package upload**: enforce a max upload size, reject non-zip content, reject
  absolute paths and `..` traversal in zip entries, extract to a temp dir,
  validate with the content loader, then atomically move into place. Content
  (including behavior scripts) is operator-installed trusted code; the
  passphrase gate is the only barrier, so MC must never be exposed publicly.
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
6. **Package install**: operator uploads a zip → MC size-checks, scans for
   traversal, extracts to temp, validates via loader → on success moves into
   the canonical root and refreshes the package index; on failure returns
   validation messages and writes nothing.
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

## 13. Delivery phases

| Phase | Scope |
| --- | --- |
| **A** | `mission-control` feature flag + `KNOWN_FEATURES`; `MCConfig`; `run_mission_control.py`; MC app skeleton, passphrase auth, static UI shell with three tabs. |
| **B** | World-side `mc_client.py` + `mc_api.py` (register/heartbeat/stats/logs/command); MC registry + heartbeat/staleness; instance list view. |
| **C** | Server Manager drilldown: log capture/polling, admin console, start/stop/restart, spawn supervisor, optional worldstate selection. |
| **D** | Package Manager: content scan, inventory view, zip upload/validate/install, enable/disable/delete; introduce `data/propsets/` loader support. |
| **E** | User Manager: direct profile DB access, search/detail/edit, audit view, resync endpoint + UI. |
| **F** | Full test coverage, README/config documentation, security review, polish. |

## 14. Open questions and future work

- **Remote registry**: fetching package/version indexes from a remote source
  (deferred; local inventory + upload only for now).
- **MC persistence**: a durable MC DB for audit/registry across restarts
  (currently in memory by design).
- **Multi-host orchestration**: managing instances on other machines,
  containers, or process supervisors beyond local children.
- **Stronger operator identity**: per-operator accounts/roles instead of a
  single shared passphrase.
- **Log streaming**: server-sent events or WebSocket streaming instead of
  polling for live log tails.
