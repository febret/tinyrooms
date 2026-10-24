# Tinyrooms — Mission Control

Status: implemented optional player-entry and operations server. Related:
[architecture](architecture.md), [database schemas](db.md),
[launch commands](../README.md#mission-control).
This is the canonical entry, lifecycle, security, and deployment contract.

## 1. Overview

MC manages world servers and a shared profile database. Public player login and
invitation-gated creation are at `/`; operator administration is at
`/mission-control`. Its four tabs are Server Manager, Package Manager, Server
Info, and User Manager. Operator access uses a separate passphrase/session;
it is neither a replacement for the in-world `\admin` console nor a sandbox
for untrusted code.

### 1.1 Enabling it

`run.py` selects MC with `TRSERVER_FEATURES=mission-control` (alias
`mission_control`). Without that flag the normal world app has no MC UI;
loading MC config without it fails. Worlds participate by setting
`TRSERVER_MC_ENDPOINT`, not by enabling the MC feature themselves.

## 2. Terminology and topology

An **instance** is one spawned or externally self-registered world-server
process, serving one world and worldstate DB. A **package** is a world,
cardset, or propset. An optional existing **template worldstate** can be selected
on start; otherwise a fresh DB is created.

```text
browser -- HTTPS :443 --> nginx -- / --> loopback HTTPS MC
                          / = player entry; /mission-control = operator UI
                          /world/<instance-id>/ --> loopback HTTPS world
MC -- spawn/supervise and token-authenticated REST --> worlds
worlds -- outbound registration/heartbeat --> MC
MC + worlds --> shared users/profiles.sqlite3
each world --> its own worldstate.sqlite3
```

Spawned and external instances share management views, but MC owns local child
processes; external lifecycle actions use cooperative world endpoints.

### 2.1 Player entry and destination resolution

- Entry and destinations must use **HTTPS on the same hostname**. Host-only
  `tr_session` (HttpOnly) and `tr_csrf` cookies use path `/`, Secure, SameSite=Lax
  and are shared across same-origin world paths. Different origins, including
  different hostnames or ports, do not share them. All participating worlds must
  use MC's shared profile DB; spawned destinations with a different users path
  are rejected.
  External instances require operator verification of that shared-DB setup.
- Resolve reads `user_profiles.profile_json.last_instance_id` **exactly** and
  validates it before any alternative. Only when that instance is no longer
  registered (or a legacy profile has zero/multiple world matches) does entry
  return explicit same-world alternatives. The player must confirm one through
  `POST /api/entry/repair`; entry never falls back automatically to the default,
  another world, or a different instance. A saved instance serving a different
  world is still rejected. Retired-instance records may rank a designated
  successor first, but confirmation remains explicit.
- Repairs preserve `last_world_id` and `remembered_room`; only the exact saved
  instance changes. If no running instance of the saved world exists, entry keeps
  the operator-restore message rather than offering another world.
- A destination must be registered/running, advertise a valid same-origin HTTPS
  `client_url` without credentials/query/fragment (normally
  `https://<hostname>/world/<instance-id>/`), and answer `/health` with matching
  world **and instance** identities. External player destinations need
  a configured stable `TRSERVER_MC_INSTANCE_ID`; an allocated transient registry
  id alone is insufficient for that health contract.
- Select **Make default** on a running instance before creating players. It
  validates readiness and an entry room, then atomically persists
  `default_instance_id` in `TRSERVER_MC_INSTANCES_PATH/entry.json`. Creation
  revalidates it, creates the account in that world's entry room, and immediately
  remembers the exact instance. Changing the default affects new accounts only.
- Set `TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE` explicitly for a stable invitation;
  otherwise it is randomized per config load. Changing invitations does not
  invalidate existing accounts. Login verifies credentials in the shared DB;
  resolve is a separate authenticated step.
- With `TRSERVER_ENTRY_URL`, a world's root redirects unauthenticated or
  mismatched world/instance profiles to entry; legacy profiles without a saved
  instance may pass the world match. Direct links do not choose a replacement
  destination. Restore the saved identity/configuration when entry fails; see
  [upgrade warnings](#83-deployment-and-upgrades).

Implementation: [entry validation/auth/default](../server/mission_control/entry.py),
[world root redirects](../server/routes/static_files.py),
[profile persistence](../server/profiles.py).

## 3. Configuration

### 3.1 Mission-control process

[MCConfig/load_mc_config](../server/mission_control/config.py) owns the full
environment inventory, defaults, aliases, and validation. Required:
`TRSERVER_FEATURES=mission-control`, `TRSERVER_MC_PASSPHRASE` (operator), and
`TRSERVER_MC_TOKEN` (fleet channel). Local listener defaults to `127.0.0.1:8001`;
users to `users`, instances to `.local/mc-instances`, versions to `.local/mc-versions`.

Operational settings:

- `TRSERVER_MC_USERS_PATH` must identify the shared profile directory.
  `TRSERVER_MC_CONTENT_PATH` defaults to the versions directory's parent;
  `TRSERVER_MC_INSTALL_PATH` overrides Server Info's auto-detected install root.
- `TRSERVER_MC_PUBLIC_ORIGIN` adds allowed origins; its first origin determines
  advertised player entry. `TRSERVER_MC_BASE_PATH` is optional; deployment uses
  an empty prefix. `TRSERVER_MC_KEEPALIVE` enables **Reboot**.
- New worlds use `TRSERVER_MC_INSTANCE_HOST` (local `127.0.0.1`), inclusive
  `TRSERVER_MC_INSTANCE_PORT_MIN`/`MAX` (`5000..5999`), and
  `TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME` (entry hostname by default; alias
  `TRSERVER_MC_INSTANCE_PUBLIC_HOST`). The public hostname must omit port/path.
  When `TRSERVER_MC_SAME_ORIGIN_WORLDS=1`, MC assigns each instance
  `/world/<instance-id>`, writes `TRSERVER_MC_WORLD_MAP`, and reloads nginx with
  `TRSERVER_MC_WORLD_MAP_RELOAD` after start/stop/delete.
- `TRSERVER_MC_INSTANCE_CERTFILE` and `TRSERVER_MC_INSTANCE_KEYFILE` must be
  paired existing files. MC itself uses [run.py](../run.py)'s self-signed helper,
  reusing `.local/cert.pem` / `key.pem` unless `--certfile`/`--keyfile` are supplied.
- `TRSERVER_MC_HEARTBEAT_SECONDS` defaults to 5; TLS verification uses
  `TRSERVER_MC_CA_FILE` or the dev-only `TRSERVER_MC_INSECURE_TLS` escape hatch.

### 3.2 World server (mission-control client)

[World configuration](../server/config.py) owns parsing/defaults. Set
`TRSERVER_MC_ENDPOINT=host:port` and matching `TRSERVER_MC_TOKEN` (missing token
is a configuration error). `TRSERVER_MC_NAME` is a display label;
`TRSERVER_MC_INSTANCE_ID` is the stable identity, distinct from world id/name.
`TRSERVER_CLIENT_URL` advertises the browser destination separately from the
management endpoint; `TRSERVER_ENTRY_URL` controls root redirects.
`TRSERVER_SHARED_CONTENT_PATH` supplies shared content (§8.4).
`TRSERVER_MC_CA_FILE` verifies MC TLS; `TRSERVER_MC_INSECURE_TLS=1` skips it.
MC supplies these settings to children; external servers must configure them.

## 4. Components and file layout

Use [MC app assembly](../server/mission_control/app.py),
[operator/fleet routes](../server/mission_control/routes.py),
[public entry](../server/mission_control/entry.py), and the
[static UI](../client/mission-control/) as the source map. [run.py](../run.py) owns
HTTPS selection/shutdown; [supervisor](../server/mission_control/supervisor.py)
owns child processes. Outbound HTTP uses async `httpx`.

### 4.1 Runtime state and persisted launch settings

MC has no separate DB. Live registration/metrics, package index, audit ring,
and operator sessions are in memory. Spawned stable identities and launch
settings persist at `<TRSERVER_MC_INSTANCES_PATH>/<instance-id>/instance.json`.
Startup restores these as unreachable; restoring identity alone does not spawn
a process. `resume.json` records children to respawn after Reboot; `entry.json`
persists the new-account default. External records rebuild through registration.
Player accounts/sessions remain in the shared profile DB.

## 5. Mission-control UI

The [UI](../client/mission-control/) uses vanilla ES modules without a build step and
project design tokens; a denser operational layout is intentional.

### 5.1 Authentication

The operator shell is public; protected API operations require an independent
MC session (401 otherwise). Passphrase login requires Origin, constant-time
comparison, and source-address rate limiting. Cookies are `tr_mc_session` and
`tr_mc_csrf`; authenticated mutations require Origin + `X-CSRF-Token`. Logout
clears the session/cookies. See [auth](../server/mission_control/auth.py) and
[routes](../server/mission_control/routes.py).

### 5.2 Tabbed shell

Four tabs share operator/version information and disconnect/error reporting.
Detailed fields and rendering live in the [UI source](../client/mission-control/).

### 5.3 Server Manager

Choose an installed code version and shared/version-bundled world; optionally
select an existing worldstate DB (blank creates fresh state), users path,
name/bind/port, features, admins, and mods. MC allocates an instance directory,
persists its launch settings, then runs that checkout's `run.py`. Use the shared
users path for player destinations. Detail provides runtime stats, bounded
stdout/stderr tails for children (polled logs for external servers), and an
admin console; log refresh can be paused.

- **Start / Stop / Restart**: MC controls children; external servers receive
  cooperative shutdown/restart. **Start** resumes a stopped spawned child with
  its saved identity/settings. Restart preserves id and saved launch settings,
  including host, base path, client URL, and version selection. If the saved
  port is unavailable, MC allocates another in-range port, updates the saved
  endpoint/identity, and logs `mc.port_reassigned` instead of failing to bind.
- **Change version**: select another installed server version for a spawned
  instance. MC re-resolves its world for that checkout, persists the selection,
  and restarts a non-stopped child. Shared worlds remain outside version roots.
  The main grid shows the running build and exposes start/restart/resync/delete
  plus version controls directly.
- **Rename**: spawned only; persists the label and restarts a non-stopped child,
  preserving id, direct URL, and any legacy base path.
- **Delete**: stops/removes a child, identity file, and resume entry; leaves
  worldstate and other data on disk. External servers are best-effort shut down
  and dropped. Deletion writes a durable retirement record, reports how many
  players have the instance saved, and accepts an optional same-world successor.
  With a successor, selected players can be reassigned immediately; otherwise
  entry offers them running same-world instances for explicit confirmation.
- **Make default**: validates/persists the new-account destination (§2.1), shown
  with a Default badge. **Resync** refreshes profiles (§11).
- **Reboot**: requires `TRSERVER_MC_KEEPALIVE`; records running/starting children
  in `resume.json`, stops spawned instances, and shuts MC down. The keepalive's
  immediate trigger/per-minute cron restarts MC; startup respawns those recorded
  children. External instances are not resumed. This differs from an ordinary
  MC restart, which restores identities but does not itself schedule children.

Lifecycle actions do not regenerate nginx; there is no **Update nginx config**
action or runtime nginx-management API. See [supervisor](../server/mission_control/supervisor.py).

### 5.4 Package Manager

[Package management](../server/mission_control/packages.py) inventories the
running build, additional version checkouts (excluding duplicate running/latest
paths), and read-only shared worlds/cardsets/propsets with validation errors.
Each checkout's own `version.json` supplies its build label. Content is managed
on disk/deployed, not uploaded through the UI.

**Delete version** removes its checkout and matching `releases/tinyrooms-<id>.tar.gz`.
The running version, path escapes, and versions with **any registered instance**
(including stopped/unreachable) are protected. Deletion is confirmed and audited.

### 5.5 User Manager

[User management](../server/mission_control/users.py) searches accounts, displays
related profile/session/inventory/reward/task/memory/audit rows, and edits
supported account fields/powers through repository methods. Edits are validated
and recorded in MC's audit ring. The detail view also shows the saved destination
and lets an operator explicitly repair it to another running same-world instance.
**Resync** targets one/all running instances and reports per-instance
success/failure; use it to refresh live clients after edits.

### 5.6 Server Info

[Server Info](../server/mission_control/server_info.py) is operator-only/read-only
and excludes token/passphrase secrets. It reports host/process/resource/config
and install storage. Linux `/proc`/load metrics show an em dash elsewhere;
host/process/disk/storage figures are cross-platform. Sampling/storage scans run
off the event loop; storage skips symlinks, caches for 60 s, and supports forced
refresh. UI metrics refresh every 5 s (toggleable); storage rescans on demand.

## 6. World-server mission-control API (`server/mc_api.py`)

[World endpoints](../server/mc_api.py) expose stats, logs, commands,
restart/shutdown, and resync under `/api/mc/*`, only with `TRSERVER_MC_ENDPOINT`.
Every request requires constant-time-checked `X-MC-Token`; rejection is 403 and
logged/audited. These are privileged endpoints, not player APIs.

MC validates commands against capabilities; the world uses the existing command
pipeline, power checks, blocking (`\r`, `\k`), and audit behavior. Execution uses
the first existing `TRSERVER_ADMINS` account in sorted username order, never a
caller-selected account. No configured account yields `admin_unavailable`; MC
does not bypass PowersService or invent in-world powers/commands.

### 6.1 World-side outbound client (`server/mc_client.py`)

[McClient](../server/mc_client.py) registers at `/api/mc/register` with stable
identity, management endpoint, public URL, base path, version/protocol, and world
identity/entry room. It retries with bounded exponential backoff, heartbeats at
the negotiated interval, and best-effort deregisters on graceful shutdown.
Unknown-instance heartbeat responses trigger re-registration. MC unavailability
or token rejection degrades management; worlds keep serving players.

## 7. Mission-control UI API

[routes.py](../server/mission_control/routes.py) is the operator/fleet route and
payload inventory. Operator mutations require session + Origin + CSRF; fleet
registration/heartbeat/deregistration use the shared token instead. Responses
use `{ok, ...}` or `{ok:false, code, message}` envelopes.

The fleet channel also exposes cross-world discovery:
`GET /api/mc/worlds` (token-authenticated) groups running instances by world and
returns each world's id, label, description, image metadata, population, online
account ids, and candidate instances with client URLs. The in-game Multiverse
activity uses this to render portals and friend presence. A participating world
still verifies that a candidate client URL shares its login hostname before
offering or travelling to it.

`GET /api/mc/instances/{world_id}/destination` (token-authenticated) resolves a
running instance serving `world_id` and returns `{ok, instance_id, world_id,
client_url, entry_room_id}`. A participating world calls it when a player uses
the Multiverse or an authored cross-world exit, then redirects the browser to
`client_url` after verifying the hostname matches so the host-only session
cookie is shared. Validation reuses the entry-destination checks
(running/registered, world identity, shared database for spawned instances, and
a matching `/health`). Unknown worlds return 404; unreachable/invalid
destinations return 503/409.

World registration includes the world's `description` and optional `image`
filename, and heartbeats include `online_account_ids` for cross-world friend
presence. These are fleet-internal fields; the world server only forwards the
viewer's friends' stickers to the activity.

### 7.1 Public player-entry API

[entry.py](../server/mission_control/entry.py) owns `/api/entry/` session,
login, create, logout, resolve, and repair. Login/create require Origin and rate
limits; logout/repair require Origin and matching session/header/cookie CSRF
tokens. A missing or ambiguous saved destination returns `409` with
`saved_instance_id`, `world_id`, `can_repair`, and same-world `candidates`;
repair revalidates the chosen instance before updating only `last_instance_id`.
Player sessions are separate from operator sessions. Destination rules are in §2.1.

## 8. Data model and storage

### 8.1 Instance registry (in memory)

[InstanceRecord/registry](../server/mission_control/registry.py) owns live state
and bounded per-instance log rings. Missing heartbeat beyond 3× the configured
interval marks an instance unreachable; child process exit marks it stopped.
Staleness changes status rather than selecting a replacement destination.
[RetiredInstanceStore](../server/mission_control/retired.py) atomically persists
deleted instance ids, world identity, deletion time, and an optional operator
successor in `<TRSERVER_MC_INSTANCES_PATH>/retired.json`; this file is advisory
for candidate ranking and survives MC restarts.

### 8.2 Profile database access

MC opens `<TRSERVER_MC_USERS_PATH>/profiles.sqlite3` through DatabaseHub and
ProfileRepository, ensuring schema compatibility and rejecting newer versions
as worlds do. MC needs no separate schema. Concurrent world/MC access relies on
WAL and short `BEGIN IMMEDIATE` repository transactions; preserve those patterns.
See [migrations](../server/state/migrations.py) and [profiles](../server/profiles.py).

### 8.3 Deployment and upgrades

[Deploy invocation](../README.md#deploying) and [tools/deploy.py](../tools/deploy.py)
are the entry points. One command handles fresh hosts and upgrades, with default
root `~/tinyrooms`; there is no operation selector. Existing installs under
`~/.local/tinyrooms` must continue passing that root explicitly or be migrated
separately. Passwordless SSH is required; missing nginx and Python
venv/pip packages are installed via apt/noninteractive sudo. Remote uploads
require `flock`, `stat`, and `sha256sum`: interrupted streams resume from their
remote byte offset and verify size/SHA-256 before installation. Releases include
their requirements; deployment installs them in the shared venv before repointing
`versions/latest`. It refreshes the fixed proxy and keepalive, restarts MC once,
and waits up to a minute for the expected version to answer its session API over
loopback HTTPS, then verifies operator login using the passphrase sourced from
`admin.env`. Failed readiness reports the MC log path. Cron runs keepalive at
reboot and every minute.

Passing `--force-restart` rolls every running spawned instance onto the deployed
version before MC itself restarts: the deploy script runs
[tools/fleet_restart.py](../tools/fleet_restart.py) from the new checkout, which
logs in over loopback, switches each running spawned child to the deployed
version (restarting it), and waits for each child to report the new build.
External instances cannot be updated and are skipped with a warning; stopped
instances are left untouched. Deployment always restarts MC once, so the flag
adds the instance rollout rather than an extra MC restart. If the rollout is
skipped (fresh install, unreachable MC) or any instance fails, deployment still
completes its own restart and readiness checks, then reports the rollout
outcome explicitly.

nginx proxies the public origin to loopback Mission Control: TCP 80 redirects to
HTTPS; 443 serves player entry `https://<hostname>/`, operator UI
`https://<hostname>/mission-control`, and same-origin worlds under
`https://<hostname>/world/<instance-id>/`. World listeners bind loopback; nginx
routes them through the generated map at `/etc/nginx/tinyrooms-worlds.map`.
Legacy `/admin` URLs redirect to root routes. [Proxy
template](../server/mission_control/nginx_template.py).

Deployment writes `<rootdir>/admin.env` with same-origin path routing,
`TRSERVER_MC_INSTANCE_HOST=127.0.0.1`, public hostname via
`TRSERVER_MC_INSTANCE_PUBLIC_HOST` (alias of `...PUBLIC_HOSTNAME`), inclusive
port bounds `10000..10999` for allocation only, empty MC base path, public entry
origin, shared users/content, and keepalive path. MC rewrites and reloads the
nginx world map on instance start/stop/delete; this requires passwordless sudo
for `install`, `nginx -t`, and `systemctl reload nginx`. Worlds reuse nginx's
`<rootdir>/nginx/certs/server.crt` / `server.key` through the paired instance TLS
settings. On a fresh host, deployment generates self-signed TLS and defaults to
`TRSERVER_MC_INSECURE_TLS=1` for management. Existing certificate/key files are
reused and checked for readability, certificate expiry, and matching public keys;
an incomplete/invalid pair fails deployment rather than being overwritten.
To replace the generated pair with a CA-issued bundle, run
[tools/install_certificates.py](../tools/install_certificates.py); it validates
the chain, backs up the previous pair, and refreshes nginx. This is not the
future hardened production launch path.

**Operator requirements:**

- Allow inbound TCP **80** and **443** in host **and provider** firewalls.
  Do not expose the internal world port range (`10000–10999`); worlds bind
  loopback and are reached only through nginx `/world/<instance-id>/` paths.
  Deployment does not open ports.
- Secrets live in `admin.env` (mode 600). Deploying-shell
  `TRSERVER_MC_PASSPHRASE`/`TRSERVER_MC_TOKEN` override existing values; otherwise
  deployment preserves them or generates first-deploy values. Set/preserve
  `TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE` for a stable invitation. Keepalive sources
  the file on startup; after editing, explicitly **Reboot** MC. Deployment also
  restarts it. Coordinate token changes with participating external worlds.
- Direct-world bind, hostname, port-range, TLS, heartbeat, management TLS, install
  path, and mod settings in `admin.env` are retained across upgrades; corresponding
  deploying-shell settings override them. Deployment-owned paths, MC listener,
  root base path, entry origin, and keepalive path are regenerated for the target.
- Upgrades refresh the fixed nginx proxy and restart MC. Already-running legacy
  worlds require stable identity, direct-public bind/URL settings, and a world
  version supporting direct entry before use as player destinations.
- **Resume preserves saved host, port, base path, and version selection**:
  loopback instances remain loopback-only; an in-range saved port that is still
  occupied during reboot is reassigned and persisted before spawn. Ports outside
  the configured range still fail an explicit new-instance start. Updating
  `admin.env` or pressing **Restart** alone is **not** a
  migration of saved launch settings. Explicitly migrate those settings while
  preserving identity and data. Resume failures do not block MC startup;
  failed entries are not retained for automatic retry. Check instance status
  and readiness after the upgrade before selecting a default/accepting players.

### 8.4 Content roots

Each checkout bundles `worlds/`, `data/cardsets/`, and `data/propsets/`. The
deploy root additionally holds shared `worlds/<id>/world.yaml`,
`cardsets/<id>/cards.yaml` (optional `pack.yaml`), and
`propsets/<id>/props.yaml`, installed on disk outside any version. Deployment
creates these roots and points MC/worlds at them.

Shared cardsets/propsets override bundled definitions on id collisions;
duplicates within one root remain errors. World-local definitions still
validate normally. World selection combines shared and chosen-version worlds,
resolving shared ids first. See [packages](../server/mission_control/packages.py)
and [content loaders](../server/content/).

### 8.5 Audit (in memory)

[MC audit](../server/mission_control/audit.py) is a bounded privileged-action ring
with actor/action/target/result/detail, surfaced by the operator API and lost on
MC restart by design. It covers auth attempts, fleet/lifecycle/default actions,
commands, resync, version deletion, and user edits; it is not a durable audit DB.

## 9. Security model

Keep MC loopback behind nginx in deployment. Public player auth does not grant
operator access; privileged fleet/user operations require their respective
session/token. Operator passphrases are constant-time compared; stored session
tokens are hashed. Preserve Origin/CSRF checks and login rate limits (§5.1/7.1).
Every MC↔world privileged call requires the shared token (403 + logged/audited
rejection). MC admin commands retain world authorization (§6).

Verify peer TLS using the configured CA bundle or normal trust store.
`TRSERVER_MC_INSECURE_TLS=1` is an explicit dev-only escape hatch; preserve MC's
startup warning and require equivalent diagnostics on world clients. Trusted
operator-installed content can include executable behavior scripts; inventory
access is privileged, not a code sandbox. Preserve
version-deletion containment/usage checks and validated/audited user edits.

## 10. Feature gating and degradation

Missing required feature/credentials fails configuration. MC outages/token
rejections leave gameplay running; entry resolution still fails when its saved
destination cannot be validated, but a removed instance now yields explicit
same-world recovery choices instead of a permanent dead end. No candidate is
selected automatically. The UI distinguishes unreachable instances; per-instance
timeouts keep dead stats/log calls from blocking the list view.

## 11. Key flows

Startup ensures the profile DB, builds inventory, restores identities, attempts
pending resume, and accepts registrations. Child start persists settings before
spawn; registration establishes running readiness. Commands follow §6.
**Resync** calls one/all worlds, bumps profile revision, and notifies live clients
to refresh, reporting refreshed/notified counts and individual failures. Worlds
currently read profiles per request; this also defines the future cache
invalidation contract. Version deletion rechecks usage before removal; stale
instances become stopped/unreachable rather than being silently replaced.

## 12. Testing strategy

Follow [contributor test placement](../AGENTS.md#writing-new-tests) and
[verification commands](../README.md#verification). MC coverage includes
[config](../tests/test_mission_control_config.py),
[auth](../tests/test_mission_control_auth.py),
[routes](../tests/test_mission_control_routes.py),
[supervision](../tests/test_mission_control_supervisor.py), and
[integration](../tests/test_mission_control_integration.py).
Use isolated profile/worldstate databases ([shared helpers](../tests/common.py));
mock HTTP transports for retry/token failures. Cover entry readiness, identity,
and default persistence along with fleet round-trips. Keep browser checks minimal
and fresh-fixture-owned; add snapshots only for reviewed rendered-state needs.

## 13. Original delivery phases

Historical sequence: A — feature/config/auth/shell; B — world channel/registry;
C — supervision/logs/console; D — version/shared-content inventory;
E — user edits/audit/resync; F — verification/docs/security/polish.

## 14. Open questions and future work

- Remote package/version registry (current inventory/content management is local).
- Durable MC audit/live-registry DB; identities/launch/resume/default already
  persist as JSON (§4.1).
- Multi-host/container/external-supervisor orchestration beyond local children.
- Per-operator accounts/roles instead of a single shared passphrase.
- SSE/WebSocket log streaming instead of polling.
