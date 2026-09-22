#!/usr/bin/env bash
set -euo pipefail

npx playwright install chromium
python -m unittest discover -s tests -v
npm run test:browser
