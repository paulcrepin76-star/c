#!/usr/bin/env bash
# Prints what the marketing stack needs. Does not start containers or change the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

python3 "$ROOT/scripts/check-marketing-compose.py"
python3 "$ROOT/scripts/preflight_marketing.py"
