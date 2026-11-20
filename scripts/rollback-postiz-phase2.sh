#!/usr/bin/env bash
# Removes the Phase 2 containers only. Mautic and its MySQL database stay running.
# Production containers, Docker networks, and ZFS datasets are not changed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

PHASE2_CONTAINERS=(
  resto-postiz
  resto-postiz-postgres
  resto-postiz-redis
  resto-marketing-db-init
  resto-temporal
  resto-temporal-postgres
  resto-temporal-elasticsearch
  resto-temporal-ui
)
MAUTIC_CONTAINERS=(
  resto-mautic
  resto-mautic-cron
  resto-mautic-worker
  resto-mautic-mysql
)

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [ "${MARKETING_PHASE2_ROLLBACK_APPROVED:-0}" != "1" ]; then
  echo "Nothing was stopped."
  echo "An approved Phase 2 rollback removes only:"
  printf '  %s\n' "${PHASE2_CONTAINERS[@]}"
  echo "It leaves these Mautic containers in place:"
  printf '  %s\n' "${MAUTIC_CONTAINERS[@]}"
  echo "Mautic data under APPDATA/mautic is kept."
  echo "Postiz and Temporal directories are kept unless MARKETING_PHASE2_ROLLBACK_DELETE_DATA=1."
  echo "  MARKETING_PHASE2_ROLLBACK_APPROVED=1 ./scripts/rollback-postiz-phase2.sh"
  exit 3
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Nothing was removed."
  exit 1
fi

if [ -n "${APPDATA:-}" ]; then
  marketing_refuse_production "$APPDATA"
fi

mautic_ids() {
  local name
  for name in "${MAUTIC_CONTAINERS[@]}"; do
    docker inspect -f '{{.Id}}' "$name" 2>/dev/null || echo "absent ${name}"
  done
}

before_mautic="$(mautic_ids)"
before_others="$(marketing_snapshot_others)"

for name in "${PHASE2_CONTAINERS[@]}"; do
  for keep in "${MAUTIC_CONTAINERS[@]}" "${PROTECTED_CONTAINERS[@]}"; do
    if [ "$keep" = "$name" ]; then
      echo "Refusing to remove ${name}."
      exit 1
    fi
  done
  if docker inspect "$name" >/dev/null 2>&1; then
    docker rm -f "$name" >/dev/null
    echo "Removed ${name}"
  else
    echo "${name} was not present"
  fi
done

after_mautic="$(mautic_ids)"
after_others="$(marketing_snapshot_others)"
if [ "$before_mautic" != "$after_mautic" ]; then
  echo "Mautic container identity changed. Phase 2 rollback must not do that."
  diff -u <(printf '%s\n' "$before_mautic") <(printf '%s\n' "$after_mautic") || true
  exit 4
fi
if [ "$before_others" != "$after_others" ]; then
  echo "A container outside Phase 2 changed. Rollback should not have done that."
  diff -u <(printf '%s\n' "$before_others") <(printf '%s\n' "$after_others") || true
  exit 4
fi

if [ "${MARKETING_PHASE2_ROLLBACK_DELETE_DATA:-0}" = "1" ]; then
  APPDATA="${APPDATA:-$ROOT/appdata}"
  base="$(cd "$APPDATA" && pwd)"
  marketing_refuse_production "$base"
  for dir in postiz temporal; do
    target="${base}/${dir}"
    case "$target" in
      "$base"/"$dir")
        if [ -d "$target" ]; then
          rm -rf "$target"
          echo "Deleted ${target}"
        fi
        ;;
      *)
        echo "Refusing odd path ${target}"
        exit 1
        ;;
    esac
  done
  if [ -d "${base}/mautic" ]; then
    echo "Kept ${base}/mautic"
  fi
else
  echo "Postiz and Temporal data directories were kept. Mautic data was kept."
fi

echo "Phase 2 rollback finished. Mautic was not removed."
