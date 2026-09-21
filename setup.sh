#!/usr/bin/env bash
set -euo pipefail

# Install Python and Node dependencies and bundle vendored browser assets.

python -m pip install -r requirements.txt
npm install
npm run vendor