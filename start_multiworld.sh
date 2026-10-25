#!/usr/bin/env bash
set -euo pipefail

# Start a local multi-world Tinyrooms: Mission Control plus the tutorial,
# scammon-academia, tiny-arcade, and tinytown world servers, all sharing one profile
# database and one advertised hostname so cross-world teleporters can hand the
# browser between ports.
#
# Usage:
#   ./start_multiworld.sh [--public-host HOSTNAME]
#
#   --public-host  Hostname or IP the browser uses and that is advertised in
#                  client URLs and Mission Control's public origin. Setting it
#                  also binds the four listeners to 0.0.0.0 so remote clients
#                  can connect. When omitted, everything stays on 127.0.0.1.
#                  Use a LAN IP or DNS name clients can reach; the self-signed
#                  certificate only covers local addresses.
#
# Ports and credentials are overridable via MC_PORT / TUTORIAL_PORT /
# SCAMMON_PORT / ARCADE_PORT / TINYTOWN_PORT (and the TRSERVER_* environment). This is a
# local-development launcher: it uses self-signed certificates and default
# development creds.

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "${TRSERVER_ADMIN_ENV:-}" ]; then
  set -a
  . "$TRSERVER_ADMIN_ENV"
  set +a
fi

PUBLIC_HOST="${PUBLIC_HOST:-}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --public-host)
      [ "$#" -ge 2 ] || { echo "--public-host requires a hostname." >&2; exit 2; }
      PUBLIC_HOST="$2"; shift 2 ;;
    -h|--help)
      echo "usage: $0 [--public-host HOSTNAME]"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -n "$PUBLIC_HOST" ]; then
  BIND_HOST="0.0.0.0"
  MGMT_HOST="127.0.0.1"
else
  BIND_HOST="127.0.0.1"
  MGMT_HOST="127.0.0.1"
  PUBLIC_HOST="127.0.0.1"
fi

MC_PORT="${MC_PORT:-8001}"
TUTORIAL_PORT="${TUTORIAL_PORT:-5100}"
SCAMMON_PORT="${SCAMMON_PORT:-5101}"
ARCADE_PORT="${ARCADE_PORT:-5102}"
BACKROOMS_PORT="${BACKROOMS_PORT:-5104}"
TINYTOWN_PORT="${TINYTOWN_PORT:-5103}"

export TRSERVER_NEW_ACCOUNT_PASSPHRASE="${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-deadbeef}"
export TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE="${TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE:-$TRSERVER_NEW_ACCOUNT_PASSPHRASE}"
export TRSERVER_MC_PASSPHRASE="${TRSERVER_MC_PASSPHRASE:-deadbeef}"
export TRSERVER_MC_TOKEN="${TRSERVER_MC_TOKEN:-deadbeef-token}"
# Scammon Academia requires the classrooms mod; load every installed mod locally.
export TRSERVER_MODS="${TRSERVER_MODS:-*}"

# A handful of authoring/activity features, but never mission-control on worlds.
WORLD_FEATURES="${WORLD_FEATURES:-dev_sample_activity,world-editor,card-database,prop-editor,cutscene-catalog}"

ROOT=".local/multiworld"
USERS="$ROOT/users"
INSTANCES="$ROOT/mc-instances"
VERSIONS="$ROOT/mc-versions"
mkdir -p "$USERS" "$INSTANCES" "$VERSIONS"

# New accounts created at mission-control entry resolve to the tutorial world.
printf '{"default_instance_id": "tutorial-1"}\n' > "$INSTANCES/entry.json"

PIDS=()
cleanup() {
  trap - EXIT INT TERM
  if [ "${#PIDS[@]}" -gt 0 ]; then
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- Mission Control ---------------------------------------------------------
TRSERVER_FEATURES=mission-control \
TRSERVER_MC_USERS_PATH="$USERS" \
TRSERVER_MC_INSTANCES_PATH="$INSTANCES" \
TRSERVER_MC_VERSIONS_PATH="$VERSIONS" \
TRSERVER_MC_INSTANCE_HOST="$BIND_HOST" \
TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME="$PUBLIC_HOST" \
TRSERVER_MC_INSTANCE_PORT_MIN=5100 \
TRSERVER_MC_INSTANCE_PORT_MAX=5199 \
TRSERVER_MC_PUBLIC_ORIGIN="https://$PUBLIC_HOST:$MC_PORT" \
TRSERVER_MC_INSECURE_TLS=1 \
python run.py --host "$BIND_HOST" --port "$MC_PORT" &
PIDS+=("$!")

# Wait until Mission Control answers before registering worlds against it.
ready=0
for _ in $(seq 1 60); do
  if python -c "import ssl, urllib.request; ssl._create_default_https_context = ssl._create_unverified_context; urllib.request.urlopen('https://$MGMT_HOST:$MC_PORT/api/entry/session', timeout=1)" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "Mission Control did not become ready on https://$MGMT_HOST:$MC_PORT." >&2
  exit 1
fi

# --- World servers -----------------------------------------------------------
start_world() {
  local world="$1" port="$2" instance_id="$3" label="$4"
  TRSERVER_FEATURES="$WORLD_FEATURES" \
  TRSERVER_WORLD_PATH="worlds/$world" \
  TRSERVER_WORLDSTATE_PATH="$ROOT/$world.sqlite3" \
  TRSERVER_USERS_PATH="$USERS" \
  TRSERVER_MC_ENDPOINT="$MGMT_HOST:$MC_PORT" \
  TRSERVER_MC_TOKEN="$TRSERVER_MC_TOKEN" \
  TRSERVER_MC_INSTANCE_ID="$instance_id" \
  TRSERVER_MC_NAME="$label" \
  TRSERVER_CLIENT_URL="https://$PUBLIC_HOST:$port" \
  TRSERVER_ENTRY_URL="https://$PUBLIC_HOST:$MC_PORT" \
  TRSERVER_MC_INSECURE_TLS=1 \
  python run.py --host "$BIND_HOST" --port "$port" &
  PIDS+=("$!")
}

start_world tutorial "$TUTORIAL_PORT" tutorial-1 "Tutorial"
start_world scammon-academia "$SCAMMON_PORT" scammon-1 "Scammon Academia"
start_world tiny-arcade "$ARCADE_PORT" arcade-1 "Tiny Arcade"
start_world tinytown "$TINYTOWN_PORT" tinytown-1 "TinyTown"
start_world tiny-backrooms "$BACKROOMS_PORT" backrooms-1 "Tiny Backrooms"

cat <<EOF
Tinyrooms multiworld is starting (bind $BIND_HOST, advertised as $PUBLIC_HOST):
  Mission Control  : https://$PUBLIC_HOST:$MC_PORT/mission-control
  Player entry     : https://$PUBLIC_HOST:$MC_PORT/
  Tutorial world   : https://$PUBLIC_HOST:$TUTORIAL_PORT/
  Scammon Academia : https://$PUBLIC_HOST:$SCAMMON_PORT/
  Tiny Arcade      : https://$PUBLIC_HOST:$ARCADE_PORT/
  TinyTown         : https://$PUBLIC_HOST:$TINYTOWN_PORT/
  Tiny Backrooms   : https://$PUBLIC_HOST:$BACKROOMS_PORT/
Mission Control manages all four worlds; the Multiverse travels between them.
Press Ctrl-C to stop everything.
EOF

wait
