#!/usr/bin/env bash
# Records host memory, CPU, disk, and container stats. Does not restart anything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${1:-}"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"

STAMP="$(date +%F-%H%M%S)"
OUT="${APPDATA:-$ROOT/appdata}/marketing-measurements"
mkdir -p "$OUT"
FILE="$OUT/${STAMP}${STAGE:+-$STAGE}.txt"
{
  echo "measured_at=$(date --iso-8601=seconds)"
  echo "stage=${STAGE:-unspecified}"
  echo
  free -h || true
  echo
  uptime || true
  echo
  df -h "${APPDATA:-$ROOT/appdata}" 2>/dev/null || df -h . || true
  echo
  appdata="${APPDATA:-$ROOT/appdata}"
  for dir in "${MARKETING_DATA_DIRS[@]}"; do
    if [ -d "${appdata}/${dir}" ]; then
      du -sh "${appdata}/${dir}" || true
    fi
  done
  echo
  if command -v docker >/dev/null 2>&1; then
    docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' || true
  else
    echo "docker not available"
  fi
} | tee "$FILE"
echo
echo "Wrote $FILE"
