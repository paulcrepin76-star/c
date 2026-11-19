#!/usr/bin/env bash
# Restores a marketing logical backup into the marketing databases only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"

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

restore_into() {
  local name="$1"
  local file="$2"
  shift 2
  for allowed in "${MARKETING_CONTAINERS[@]}"; do
    if [ "$allowed" = "$name" ]; then
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
      return 0
    fi
  done
  echo "Refusing to exec into ${name}."
  exit 1
}

restore_into resto-mautic-mysql "$src/mautic.sql" sh -c 'mysql --user="$MYSQL_USER" --password="$MYSQL_PASSWORD"'
restore_into resto-postiz-postgres "$src/postiz.sql" sh -c 'psql -U postiz -d postiz'
restore_into resto-postiz-postgres "$src/command.sql" sh -c 'psql -U postiz -d command'
restore_into resto-temporal-postgres "$src/temporal.sql" sh -c 'psql -U temporal -d postgres'
echo "Restore finished. resto-postgres was not contacted."
