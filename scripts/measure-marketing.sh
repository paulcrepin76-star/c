#!/usr/bin/env bash
# Records host memory and container RSS. Does not restart anything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

STAMP="$(date +%F-%H%M%S)"
OUT="${APPDATA:-$ROOT/appdata}/marketing-measurements"
mkdir -p "$OUT"
FILE="$OUT/$STAMP.txt"
{
  echo "measured_at=$(date --iso-8601=seconds)"
  echo
  free -h || true
  echo
  if command -v docker >/dev/null 2>&1; then
    docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' || true
  else
    echo "docker not available"
  fi
} | tee "$FILE"
echo
echo "Wrote $FILE"
