#!/usr/bin/env bash
# Prints what the marketing stack needs. Does not start containers or change the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

ENV_FILE="${MARKETING_ENV_FILE:-$ROOT/.env}"
if [ -n "${MARKETING_ENV_FILE:-}" ]; then
  marketing_refuse_production "$ENV_FILE"
fi
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
fi

if [ -n "${APPDATA:-}" ]; then
  marketing_refuse_production "$APPDATA"
fi

py="$("$ROOT/scripts/ensure-private-python.sh")"
"$py" "$ROOT/scripts/check-marketing-compose.py"
"$py" "$ROOT/scripts/preflight_marketing.py"
