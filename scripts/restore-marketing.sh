#!/usr/bin/env bash
# Restores a marketing logical backup into the marketing databases only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

src="${1:-}"
if [ "${MARKETING_RESTORE_APPROVED:-0}" != "1" ]; then
  echo "Nothing was restored. Pass the backup directory created by backup-marketing.sh:"
  echo "  MARKETING_RESTORE_APPROVED=1 ./scripts/restore-marketing.sh /mnt/user/backups/resto-marketing/STAMP"
  exit 3
fi

if [ -z "$src" ] || [ ! -d "$src" ]; then
  echo "Backup directory not found. Nothing was restored."
  exit 1
fi

MAUTIC_DB_CONTAINER="${MAUTIC_DB_CONTAINER:-resto-mautic-mysql}"
POSTIZ_DB_CONTAINER="${POSTIZ_DB_CONTAINER:-resto-postiz-postgres}"
TEMPORAL_DB_CONTAINER="${TEMPORAL_DB_CONTAINER:-resto-temporal-postgres}"

refuse_protected() {
  local name="$1"
  local keep
  for keep in "${PROTECTED_CONTAINERS[@]}"; do
    if [ "$keep" = "$name" ]; then
      echo "Refusing to exec into protected container ${name}."
      exit 1
    fi
  done
}

restore_into() {
  local name="$1"
  local file="$2"
  shift 2
  refuse_protected "$name"
  if [ ! -f "$file" ]; then
    echo "Missing ${file}. That database was left untouched."
    return 0
  fi
  if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    echo "${name} is not running. ${file} was not loaded."
    return 1
  fi
  docker exec -i "$name" "$@" < "$file"
  echo "Loaded ${file} into ${name}"
}

restore_into "$MAUTIC_DB_CONTAINER" "$src/mautic.sql" sh -c 'mysql --user=root --password="$MYSQL_ROOT_PASSWORD"'
restore_into "$POSTIZ_DB_CONTAINER" "$src/postiz.sql" sh -c 'psql -U postiz -d postiz -v ON_ERROR_STOP=1'
restore_into "$POSTIZ_DB_CONTAINER" "$src/command.sql" sh -c 'psql -U postiz -d command -v ON_ERROR_STOP=1'
if [ -f "$src/temporal.sql" ]; then
  restore_into "$TEMPORAL_DB_CONTAINER" "$src/temporal.sql" sh -c 'psql -U temporal -d postgres -v ON_ERROR_STOP=1'
fi
for file in "$src"/temporal-*.sql; do
  [ -f "$file" ] || continue
  base="$(basename "$file" .sql)"
  db="${base#temporal-}"
  restore_into "$TEMPORAL_DB_CONTAINER" "$file" sh -c "psql -U temporal -d ${db} -v ON_ERROR_STOP=1"
done
echo "Restore finished. resto-postgres was not contacted."
