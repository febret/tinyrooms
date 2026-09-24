#!/bin/bash

#!/usr/bin/env bash
set -euo pipefail

export TRSERVER_NEW_ACCOUNT_PASSPHRASE=deadbeef
# Load every installed mod by default for local development.
export TRSERVER_MODS="${TRSERVER_MODS:-*}"
# Enable the authoring applications (World Editor + Card Database) locally.
export TRSERVER_FEATURES="${TRSERVER_FEATURES:-dev_sample_activity,world-editor,card-database}"
# Grant admin (which includes editor access) to a local account, e.g.:
# export TRSERVER_ADMINS="${TRSERVER_ADMINS:-}"

if [[ -z "${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-}" ]]; then
  echo "Set TRSERVER_NEW_ACCOUNT_PASSPHRASE before starting Tinyrooms." >&2
  exit 1
fi

# Run ./setup.sh once to install and bundle dependencies, then start the game.
python run.py "$@"