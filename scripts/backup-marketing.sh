#!/usr/bin/env bash
# Logical dumps of the marketing databases only. Does not dump resto-postgres and does not stop anything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

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
echo "The marketing .env is not in this dump. Encrypt it with scripts/backup-marketing-env.sh."
echo "  MARKETING_BACKUP_APPROVED=1 ./scripts/backup-marketing.sh"
  exit 3
fi

APPDATA="${APPDATA:-$ROOT/appdata}"
marketing_refuse_production "$APPDATA"
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

dump_running() {
  local name="$1"
  refuse_protected "$name"
  if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    return 0
  fi
  echo "${name} is not running. Its dump was skipped."
  return 1
}

if dump_running "$MAUTIC_DB_CONTAINER"; then
  docker exec "$MAUTIC_DB_CONTAINER" sh -c 'mysqldump --user=root --password="$MYSQL_ROOT_PASSWORD" --single-transaction --add-drop-database --databases "$MYSQL_DATABASE"' > "$dest/mautic.sql"
  echo "Wrote $dest/mautic.sql"
fi

dump_pg() {
  local name="$1"
  local user="$2"
  local db="$3"
  local file="$4"
  if docker exec "$name" psql -U "$user" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
    docker exec "$name" pg_dump -U "$user" -d "$db" --clean --if-exists > "$file"
    echo "Wrote $file"
  else
    echo "${db} is not in ${name}. It was left out of the backup."
  fi
}

if dump_running "$POSTIZ_DB_CONTAINER"; then
  dump_pg "$POSTIZ_DB_CONTAINER" postiz postiz "$dest/postiz.sql"
  dump_pg "$POSTIZ_DB_CONTAINER" postiz command "$dest/command.sql"
fi

if dump_running "$TEMPORAL_DB_CONTAINER"; then
  databases="$(docker exec "$TEMPORAL_DB_CONTAINER" psql -U temporal -d postgres -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname <> 'postgres'")"
  for db in $databases; do
    dump_pg "$TEMPORAL_DB_CONTAINER" temporal "$db" "$dest/temporal-${db}.sql"
  done
fi

cat > "$dest/README.txt" <<EOF
Marketing logical backup ${stamp}
These dumps do not include resto-postgres, n8n, or uploaded media.
They also do not include the marketing .env. That file lives in the source checkout and holds database passwords and encryption keys.
Encrypt it with scripts/backup-marketing-env.sh.
Also keep the Unraid appdata backup of ${APPDATA}/mautic, postiz, temporal, command, and caddy.
Restore with MARKETING_RESTORE_APPROVED=1 ./scripts/restore-marketing.sh ${dest}
EOF

echo "Backup directory: $dest"
