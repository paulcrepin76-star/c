#!/usr/bin/env bash
# Proves backup and restore against throwaway databases.
# Refuses to run on Unraid and never uses the resto-* container names.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -d /mnt/user ]; then
  echo "This isolated test refuses to run on Unraid. Nothing was started."
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not available here. The isolated restore was not run."
  exit 2
fi

tmp="$(mktemp -d)"
cleanup() {
  docker rm -f marketingtest-mysql marketingtest-pg-postiz marketingtest-pg-temporal >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

echo "Starting throwaway MySQL 8.4.13 and Postgres 17.12 and 16.16. These names are marketingtest-*, not resto-*."
docker run -d --name marketingtest-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpw \
  -e MYSQL_DATABASE=mautic \
  -e MYSQL_USER=mautic \
  -e MYSQL_PASSWORD=mauticpw \
  mysql:8.4.13 >/dev/null
docker run -d --name marketingtest-pg-postiz \
  -e POSTGRES_USER=postiz \
  -e POSTGRES_PASSWORD=postizpw \
  -e POSTGRES_DB=postiz \
  postgres:17.12-alpine >/dev/null
docker run -d --name marketingtest-pg-temporal \
  -e POSTGRES_USER=temporal \
  -e POSTGRES_PASSWORD=temporalpw \
  -e POSTGRES_DB=temporal \
  postgres:16.16 >/dev/null

wait_mysql() {
  local i
  for i in $(seq 1 60); do
    if docker exec marketingtest-mysql mysqladmin --user=mautic --password=mauticpw ping >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "MySQL did not become ready."
  exit 1
}
wait_pg() {
  local name="$1"
  local user="$2"
  local i
  for i in $(seq 1 60); do
    if docker exec "$name" pg_isready -U "$user" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "$name did not become ready."
  exit 1
}
wait_mysql
wait_pg marketingtest-pg-postiz postiz
wait_pg marketingtest-pg-temporal temporal

docker exec marketingtest-pg-postiz psql -U postiz -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE command OWNER postiz"
docker exec marketingtest-mysql mysql --user=mautic --password=mauticpw mautic -e "CREATE TABLE proof (id INT PRIMARY KEY, note VARCHAR(40)); INSERT INTO proof VALUES (1, 'paella');"
docker exec marketingtest-pg-postiz psql -U postiz -d postiz -v ON_ERROR_STOP=1 -c "CREATE TABLE proof (id int primary key, note text); INSERT INTO proof VALUES (1, 'postiz-row');"
docker exec marketingtest-pg-postiz psql -U postiz -d command -v ON_ERROR_STOP=1 -c "CREATE TABLE proof (id int primary key, note text); INSERT INTO proof VALUES (1, 'command-row');"
docker exec marketingtest-pg-temporal psql -U temporal -d temporal -v ON_ERROR_STOP=1 -c "CREATE TABLE proof (id int primary key, note text); INSERT INTO proof VALUES (1, 'temporal-row');"

mkdir -p "$tmp/appdata" "$tmp/backups"
backup_log="$(
  MARKETING_BACKUP_APPROVED=1 \
  MARKETING_BACKUP_DIR="$tmp/backups" \
  APPDATA="$tmp/appdata" \
  MAUTIC_DB_CONTAINER=marketingtest-mysql \
  POSTIZ_DB_CONTAINER=marketingtest-pg-postiz \
  TEMPORAL_DB_CONTAINER=marketingtest-pg-temporal \
  "$ROOT/scripts/backup-marketing.sh"
)"
echo "$backup_log"
dest="$(printf '%s\n' "$backup_log" | awk -F': ' '/^Backup directory: / {print $2}')"
if [ -z "$dest" ] || [ ! -d "$dest" ]; then
  echo "Backup directory was not created."
  exit 1
fi

docker exec marketingtest-mysql mysql --user=mautic --password=mauticpw mautic -e "DROP TABLE proof;"
docker exec marketingtest-pg-postiz psql -U postiz -d postiz -c "DROP TABLE proof;"
docker exec marketingtest-pg-postiz psql -U postiz -d command -c "DROP TABLE proof;"
docker exec marketingtest-pg-temporal psql -U temporal -d temporal -c "DROP TABLE proof;"

MARKETING_RESTORE_APPROVED=1 \
  MAUTIC_DB_CONTAINER=marketingtest-mysql \
  POSTIZ_DB_CONTAINER=marketingtest-pg-postiz \
  TEMPORAL_DB_CONTAINER=marketingtest-pg-temporal \
  "$ROOT/scripts/restore-marketing.sh" "$dest"

mysql_note="$(docker exec marketingtest-mysql mysql --user=mautic --password=mauticpw --batch --skip-column-names mautic -e "SELECT note FROM proof WHERE id=1;")"
postiz_note="$(docker exec marketingtest-pg-postiz psql -U postiz -d postiz -tAc "SELECT note FROM proof WHERE id=1;")"
command_note="$(docker exec marketingtest-pg-postiz psql -U postiz -d command -tAc "SELECT note FROM proof WHERE id=1;")"
temporal_note="$(docker exec marketingtest-pg-temporal psql -U temporal -d temporal -tAc "SELECT note FROM proof WHERE id=1;")"

test "$mysql_note" = "paella"
test "$postiz_note" = "postiz-row"
test "$command_note" = "command-row"
test "$temporal_note" = "temporal-row"
echo "Isolated restore returned paella, postiz-row, command-row, and temporal-row."
echo "resto-postgres was not created or contacted."
