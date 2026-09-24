#!/usr/bin/env bash
set -euo pipefail

export TRSERVER_NEW_ACCOUNT_PASSPHRASE="${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-deadbeef}"
# Load every installed mod by default for local development.
export TRSERVER_MODS="${TRSERVER_MODS:-*}"
# Enable the authoring applications (World Editor + Card Database) locally.
# Set TRSERVER_FEATURES=mission-control to launch the mission-control server instead.
export TRSERVER_FEATURES="${TRSERVER_FEATURES:-dev_sample_activity,world-editor,card-database}"
# Grant admin (which includes editor access) to a local account, e.g.:
# export TRSERVER_ADMINS="${TRSERVER_ADMINS:-}"

# Mission-control development defaults (override in the environment for real deployments).
if [[ "${TRSERVER_FEATURES}" == *mission-control* || "${TRSERVER_FEATURES}" == *mission_control* ]]; then
  export TRSERVER_MC_PASSPHRASE="${TRSERVER_MC_PASSPHRASE:-deadbeef}"
  export TRSERVER_MC_TOKEN="${TRSERVER_MC_TOKEN:-deadbeef-token}"
fi

if [[ -z "${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-}" ]]; then
  echo "Set TRSERVER_NEW_ACCOUNT_PASSPHRASE before starting Tinyrooms." >&2
  exit 1
fi

# Run ./setup.sh once to install and bundle dependencies, then start the server.
# run.py launches mission control when TRSERVER_FEATURES includes mission-control.
python run.py "$@"
