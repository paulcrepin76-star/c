#!/usr/bin/env bash
# Removes resto-command only. Mautic, Postiz, Temporal, and production containers stay.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

KEEP_CONTAINERS=(
  resto-mautic
  resto-mautic-mysql
  resto-mautic-cron
  resto-mautic-worker
  resto-postiz
  resto-postiz-postgres
  resto-postiz-redis
  resto-marketing-db-init
  resto-temporal
  resto-temporal-postgres
  resto-temporal-elasticsearch
  resto-temporal-ui
  "${PROTECTED_CONTAINERS[@]}"
)

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [ "${MARKETING_PHASE3_ROLLBACK_APPROVED:-0}" != "1" ]; then
  echo "Nothing was stopped."
  echo "An approved Phase 3 rollback removes only resto-command."
  echo "Mautic, Postiz, Temporal, production containers, and the command database are kept."
  echo "The command data directory is kept unless MARKETING_PHASE3_ROLLBACK_DELETE_DATA=1."
  echo "  MARKETING_PHASE3_ROLLBACK_APPROVED=1 ./scripts/rollback-dashboard-phase3.sh"
  exit 3
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Nothing was removed."
  exit 1
fi

if [ -n "${APPDATA:-}" ]; then
  marketing_refuse_production "$APPDATA"
fi

kept_ids() {
  local name
  for name in "${KEEP_CONTAINERS[@]}"; do
    docker inspect -f '{{.Id}}' "$name" 2>/dev/null || echo "absent ${name}"
  done
}

before="$(kept_ids)"
if docker inspect resto-command >/dev/null 2>&1; then
  docker rm -f resto-command >/dev/null
  echo "Removed resto-command"
else
  echo "resto-command was not present"
fi
after="$(kept_ids)"
if [ "$before" != "$after" ]; then
  echo "A container other than resto-command changed. That was not supposed to happen."
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 4
fi

if [ "${MARKETING_PHASE3_ROLLBACK_DELETE_DATA:-0}" = "1" ]; then
  if [ -z "${APPDATA:-}" ]; then
    echo "APPDATA is unset. No files were deleted."
    exit 1
  fi
  target="${APPDATA%/}/command"
  case "$target" in
    /mnt/cache/appdata/surveycafe-marketing/command) ;;
    *)
      echo "Refusing to delete ${target}."
      exit 1
      ;;
  esac
  rm -rf "$target"
  echo "Deleted ${target}"
else
  echo "Command files were kept."
fi
echo "Mautic and Postiz were not removed."
