#!/usr/bin/env bash
set -euo pipefail

# Start a local multi-world Tinyrooms. Worlds, ports, labels, instance ids, and
# mods are read from multiworld.json; the Python launcher handles Mission
# Control plus the configured world servers and shared profile database.
#
# Usage:
#   ./start_multiworld.sh [--public-host HOSTNAME] [--config PATH]
#
#   --public-host  Hostname or IP the browser uses and that is advertised in
#                  client URLs and Mission Control's public origin. Setting it
#                  also binds the listeners to 0.0.0.0 so remote clients can
#                  connect. When omitted, everything stays on 127.0.0.1.
#   --config       Alternate multiworld JSON file. Defaults to multiworld.json.
#
# Mission Control's port and credentials are overridable via MC_PORT and the
# TRSERVER_* environment. Per-world ports can be overridden with
# MULTIWORLD_<WORLD>_PORT or the legacy *_PORT variables. This is a
# local-development launcher: it uses self-signed certificates and default
# development creds.

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "${TRSERVER_ADMIN_ENV:-}" ]; then
  set -a
  . "$TRSERVER_ADMIN_ENV"
  set +a
fi

exec python start_multiworld.py "$@"
