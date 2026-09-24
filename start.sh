#!/bin/bash

#!/usr/bin/env bash
set -euo pipefail

export TRSERVER_NEW_ACCOUNT_PASSPHRASE=deadbeef
# Load every installed mod by default for local development.
export TRSERVER_MODS="${TRSERVER_MODS:-*}"

if [[ -z "${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-}" ]]; then
  echo "Set TRSERVER_NEW_ACCOUNT_PASSPHRASE before starting Tinyrooms." >&2
  exit 1
fi

# Run ./setup.sh once to install and bundle dependencies, then start the game.
python run.py "$@"