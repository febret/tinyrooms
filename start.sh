#!/bin/bash

#!/usr/bin/env bash
set -euo pipefail

export TRSERVER_NEW_ACCOUNT_PASSPHRASE=deadbeef

if [[ -z "${TRSERVER_NEW_ACCOUNT_PASSPHRASE:-}" ]]; then
  echo "Set TRSERVER_NEW_ACCOUNT_PASSPHRASE before starting Tinyrooms." >&2
  exit 1
fi

python -m pip install -r requirements.txt
npm install
npm run vendor
python run.py "$@"