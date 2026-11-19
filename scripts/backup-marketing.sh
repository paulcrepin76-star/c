#!/usr/bin/env bash
# Logical dumps of the marketing databases only. Does not dump resto-postgres and does not stop anything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [ "${MARKETING_BACKUP_APPROVED:-0}" != "1" ]; then
  echo "Nothing was dumped. This script reads only these containers when they are running:"
  printf '  %s\n' resto-mautic-mysql resto-postiz-postgres resto-temporal-postgres
  echo "It writes SQL files under MARKETING_BACKUP_DIR, which must be outside APPDATA."
  echo "On Unraid the default is /mnt/user/backups/resto-marketing when that parent exists."
  echo "  MARKETING_BACKUP_APPROVED=1 ./scripts/backup-marketing.sh"
  exit 3
fi

APPDATA="${APPDATA:-$ROOT/appdata}"
if [ -z "${MARKETING_BACKUP_DIR:-}" ]; then
  if [ -d /mnt/user/backups ]; then
    MARKETING_BACKUP_DIR=/mnt/user/backups/resto-marketing
  else
    echo "Set MARKETING_BACKUP_DIR to a path outside ${APPDATA}. Nothing was dumped."
    exit 1
  fi
fi

case "$MARKETING_BACKUP_DIR" in
  "$APPDATA"|"$APPDATA"/*)
    echo "Refusing to store backups inside ${APPDATA}. Nothing was dumped."
    exit 1
    ;;
esac

stamp="$(date +%F-%H%M%S)"
dest="${MARKETING_BACKUP_DIR}/${stamp}"
mkdir -p "$dest"
chmod 700 "$dest"

dump_running() {
  local name="$1"
  for allowed in "${MARKETING_CONTAINERS[@]}"; do
    if [ "$allowed" = "$name" ]; then
      if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
        return 0
      fi
      echo "${name} is not running. Its dump was skipped."
      return 1
    fi
  done
  echo "Refusing to exec into ${name}. It is not a marketing container."
  exit 1
}

if dump_running resto-mautic-mysql; then
  docker exec resto-mautic-mysql sh -c 'mysqldump --user="$MYSQL_USER" --password="$MYSQL_PASSWORD" --single-transaction --databases "$MYSQL_DATABASE"' > "$dest/mautic.sql"
  echo "Wrote $dest/mautic.sql"
fi

if dump_running resto-postiz-postgres; then
  docker exec resto-postiz-postgres sh -c 'pg_dump -U postiz -d postiz' > "$dest/postiz.sql"
  docker exec resto-postiz-postgres sh -c 'pg_dump -U postiz -d command' > "$dest/command.sql"
  echo "Wrote $dest/postiz.sql and $dest/command.sql"
fi

if dump_running resto-temporal-postgres; then
  docker exec resto-temporal-postgres sh -c 'pg_dumpall -U temporal' > "$dest/temporal.sql"
  echo "Wrote $dest/temporal.sql"
fi

cat > "$dest/README.txt" <<EOF
Marketing logical backup ${stamp}
These dumps do not include resto-postgres, n8n, or uploaded media.
Also keep the Unraid appdata backup of ${APPDATA}/mautic, postiz, temporal, command, and caddy.
Restore with MARKETING_RESTORE_APPROVED=1 ./scripts/restore-marketing.sh ${dest}
EOF

echo "Backup directory: $dest"
