#!/usr/bin/env bash
# Prints what the marketing stack needs. Does not start containers or change the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [ -n "${APPDATA:-}" ]; then
  marketing_refuse_production "$APPDATA"
fi

py="$("$ROOT/scripts/ensure-private-python.sh")"
"$py" "$ROOT/scripts/check-marketing-compose.py"
"$py" "$ROOT/scripts/preflight_marketing.py"
