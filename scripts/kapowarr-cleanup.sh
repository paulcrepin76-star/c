#!/usr/bin/env bash
# Clean Kapowarr over its HTTP API. Does not delete volume folders.
# From this Cloud Agent the UI is proxied at http://127.0.0.1:5656.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
export KAPOWARR_URL="${KAPOWARR_URL:-http://127.0.0.1:5656/api}"
export KAPOWARR_API_KEY_FILE="${KAPOWARR_API_KEY_FILE:-/tmp/kapowarr-api-key}"

exec python3 "$ROOT/scripts/kapowarr_cleanup.py" "$@"
