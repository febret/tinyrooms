#!/usr/bin/env bash
set -euo pipefail

TR_UPDATE_SCREENSHOTS=1 npm run test:visual -- --update-snapshots
