#!/usr/bin/env bash
# Starts the Survey Café marketing dashboard after Mautic and Postiz are healthy.
# Backs up databases and the marketing .env first.
# Starts only resto-command. It does not recreate Mautic, Postiz, Temporal, or production containers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env-crypto.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
marketing_refuse_production "$ROOT"

ancestor_phase2="9a17991cb4b0ea0998bb34c79eaa1a838d5a36d8"
ancestor_phase1="99b5b0dd3d54ba5752d710a84d53e7c02449c748"
want_data="/mnt/cache/appdata/surveycafe-marketing"
want_bind="100.116.48.120"
tmp=""

MAUTIC_CONTAINERS=(
  resto-mautic
  resto-mautic-mysql
  resto-mautic-cron
  resto-mautic-worker
)
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
KEEP_CONTAINERS=(
  "${MAUTIC_CONTAINERS[@]}"
  "${PHASE2_CONTAINERS[@]}"
  "${PROTECTED_CONTAINERS[@]}"
)

cleanup() {
  if [ -n "$tmp" ] && [ -d "$tmp" ]; then
    rm -rf "$tmp"
  fi
}
trap cleanup EXIT

report_marketing_containers() {
  local name state
  echo "Marketing container state:"
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not available, so container state could not be read."
    return 0
  fi
  for name in "${MARKETING_CONTAINERS[@]}"; do
    if state="$(docker inspect -f '{{.Name}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null)"; then
      printf '%s\n' "$state"
    else
      echo "${name} status=absent"
    fi
  done
}

stop() {
  local code="$1"
  shift
  if [ "$#" -gt 0 ]; then
    printf '%s\n' "$@"
  fi
  if [ "$code" -ne 3 ]; then
    report_marketing_containers
  fi
  exit "$code"
}

kept_ids() {
  local name
  for name in "${KEEP_CONTAINERS[@]}"; do
    docker inspect -f '{{.Name}} {{.Id}}' "$name" 2>/dev/null || echo "absent ${name}"
  done
}

require_kept_unchanged() {
  local now
  now="$(kept_ids)"
  if [ "$now" != "$kept_before" ]; then
    echo "An existing container identity changed. Phase 3 may start only resto-command."
    diff -u <(printf '%s\n' "$kept_before") <(printf '%s\n' "$now") || true
    stop 4
  fi
}

require_healthy() {
  local name="$1"
  if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    stop 1 "Refusing: ${name} is not running. Phase 3 does not install it. Nothing was started."
  fi
  if ! docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null | grep -qx healthy; then
    stop 1 "Refusing: ${name} is not healthy. Phase 3 does not recreate it. Nothing was started."
  fi
}

require_running() {
  local name="$1"
  if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    stop 1 "Refusing: ${name} is not running. Phase 3 does not start it. Nothing was started."
  fi
}

verify_env_backup() {
  local out="$1"
  local enc actual expected
  enc="$(awk -F': ' '/^Encrypted marketing \.env: / {print $2}' "$out" | head -1)"
  [ -n "$enc" ] && [ -f "$enc" ] || return 1
  [ "$(stat -c '%a' "$enc")" = "600" ] || return 1
  actual="$(sha256sum "$enc" | awk '{print $1}')"
  expected="$(awk 'NF {print $1; exit}' "${enc}.sha256")"
  [ -n "$expected" ] && [ "$actual" = "$expected" ] || return 1
  printf '%s\n' "$enc"
}

if [ "${MARKETING_PHASE3_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started."
  echo "Phase 3 starts resto-command on ${want_bind}:8090 after Mautic and Postiz are healthy."
  echo "It does not recreate Mautic, Postiz, Temporal, or production containers."
  echo "It does not change vm.max_map_count, ZFS, or Docker networks, and it does not start Caddy."
  echo "  MARKETING_ENV_PASSPHRASE='...' MARKETING_DEPLOY_COMMIT=<sha> MARKETING_PHASE3_APPROVED=1 ./scripts/deploy-dashboard-phase3.sh"
  exit 3
fi

unset MARKETING_MEMORY_ACK MARKETING_LOAD_ACK MARKETING_MAP_COUNT_APPROVED
unset MARKETING_PUBLIC_APPROVED MARKETING_DASHBOARD_APPROVED
umask 077

deploy_commit="$(printf '%s' "${MARKETING_DEPLOY_COMMIT:-}" | tr '[:upper:]' '[:lower:]')"
if ! printf '%s\n' "$deploy_commit" | grep -Eq '^[0-9a-f]{40}$'; then
  stop 1 "Refusing: MARKETING_DEPLOY_COMMIT must be the full 40-character SHA. A branch name is not accepted. Nothing was started."
fi
if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  stop 1 "Refusing: ${ROOT} is not a Git checkout. Nothing was started."
fi
head_commit="$(git -C "$ROOT" rev-parse HEAD)"
if [ "$head_commit" != "$deploy_commit" ]; then
  stop 1 "Refusing: HEAD is ${head_commit}. The pinned deployment commit is ${deploy_commit}. Nothing was started."
fi
for needed in "$ancestor_phase2" "$ancestor_phase1"; do
  if ! git -C "$ROOT" merge-base --is-ancestor "$needed" HEAD; then
    stop 1 "Refusing: HEAD ${head_commit} does not contain ${needed}. Nothing was started."
  fi
done
echo "Pinned deployment commit ${head_commit}."

if [ -z "${MARKETING_ENV_PASSPHRASE:-}" ] || [ "${#MARKETING_ENV_PASSPHRASE}" -lt 16 ]; then
  stop 6 "The backup passphrase was rejected. Phase 3 requires it before any backup or container change. Nothing was started."
fi
tmp="$(mktemp -d)"
printf 'passphrase-check\n' > "$tmp/sample"
if ! marketing_env_encrypt "$tmp/sample" "$tmp/sample.enc" 2>"$tmp/openssl.err"; then
  stop 6 "The backup passphrase was rejected by the encryption tool. Nothing was started."
fi
if ! marketing_env_decrypt "$tmp/sample.enc" "$tmp/sample.out" 2>"$tmp/openssl.err"; then
  stop 6 "The backup passphrase could not decrypt a verification sample. Nothing was started."
fi
if ! cmp -s "$tmp/sample" "$tmp/sample.out"; then
  stop 6 "The backup passphrase failed verification. Nothing was started."
fi
echo "Backup passphrase verified. It was not printed."

if [ ! -f "$ROOT/.env" ] || [ -L "$ROOT/.env" ]; then
  stop 1 "Refusing: the working marketing .env must already exist. Phase 3 does not copy .env.example over it. Nothing was started."
fi
appdata="$(marketing_env_value "$ROOT/.env" APPDATA)"
bind="$(marketing_env_value "$ROOT/.env" BIND_ADDR)"
if [ "$appdata" != "$want_data" ]; then
  stop 1 "Refusing: APPDATA is ${appdata:-unset}. It must be ${want_data}. Nothing was started."
fi
if [ "$bind" != "$want_bind" ]; then
  stop 1 "Refusing: BIND_ADDR is ${bind:-unset}. It must be ${want_bind}. Nothing was started."
fi
marketing_require_separate_paths "$ROOT" "$appdata"

if ! command -v docker >/dev/null 2>&1; then
  stop 1 "Docker is not available. Nothing was started."
fi
if docker inspect resto-command >/dev/null 2>&1; then
  stop 1 "Refusing: resto-command already exists. Phase 3 will not recreate it. Nothing was started."
fi
require_healthy resto-mautic
require_running resto-mautic-mysql
require_running resto-mautic-cron
require_running resto-mautic-worker
require_healthy resto-postiz
require_running resto-postiz-postgres
require_running resto-postiz-redis
temporal_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' resto-temporal 2>/dev/null || echo missing)"
if [ "$temporal_health" != "healthy" ]; then
  echo "Refusing: resto-temporal health is ${temporal_health}."
  echo "The healthcheck is: temporal operator cluster health --address 127.0.0.1:7233."
  echo "A running container is not enough. Phase 3 does not restart Temporal and does not start the dashboard."
  stop 1
fi
echo "Mautic and Postiz containers are healthy. Postiz homepage health is not the public API authentication test. That test is still unresolved."
echo "Their containers will not be recreated."
kept_before="$(kept_ids)"

stamp="$(date +%Y%m%d-%H%M%S)"
set +e
MARKETING_BACKUP_APPROVED=1 \
  MARKETING_BACKUP_REQUIRE_MAUTIC=1 \
  MARKETING_BACKUP_STAMP="phase3-${stamp}" \
  "$ROOT/scripts/backup-marketing.sh" >"$tmp/db.out" 2>"$tmp/db.err"
db_code=$?
set -e
cat "$tmp/db.out"
cat "$tmp/db.err" >&2
if [ "$db_code" -ne 0 ]; then
  echo "The database backup failed. The dashboard was not started."
  stop 7
fi
db_dir="$(awk -F': ' '/^Backup directory: / {print $2}' "$tmp/db.out" | head -1)"
for required in mautic.sql postiz.sql; do
  if [ -z "$db_dir" ] || [ ! -s "${db_dir}/${required}" ]; then
    echo "The ${required} backup is missing. The dashboard was not started."
    stop 7
  fi
done
if ! grep -q "Dump completed" "${db_dir}/mautic.sql"; then
  echo "The Mautic database backup is incomplete. The dashboard was not started."
  stop 7
fi
if ! grep -q "PostgreSQL database dump" "${db_dir}/postiz.sql"; then
  echo "The Postiz database backup is incomplete. The dashboard was not started."
  stop 7
fi
echo "Verified Mautic and Postiz database backups in ${db_dir}."

set +e
MARKETING_ENV_BACKUP_APPROVED=1 \
  MARKETING_ENV_BACKUP_STAMP="phase3-${stamp}-before" \
  "$ROOT/scripts/backup-marketing-env.sh" >"$tmp/env-before.out" 2>"$tmp/env-before.err"
env_before_code=$?
set -e
cat "$tmp/env-before.out"
cat "$tmp/env-before.err" >&2
if [ "$env_before_code" -ne 0 ] || ! env_before="$(verify_env_backup "$tmp/env-before.out")"; then
  echo "The encrypted configuration backup failed. The dashboard was not started."
  stop 7
fi
echo "Verified encrypted configuration backup: ${env_before}"
chmod 600 "$ROOT/.env"
require_kept_unchanged

echo "Checking RAM, CPU, the resto network, storage, and port 8090."
if ! MARKETING_STAGE=dashboard MARKETING_ENV_FILE="$ROOT/.env" "$ROOT/scripts/preflight-marketing.sh"; then
  echo "Preflight failed. resto-command was not started."
  require_kept_unchanged
  stop 2
fi

command_password="$(marketing_env_value "$ROOT/.env" COMMAND_DB_PASSWORD)"
case "$command_password" in
  ""|change-me|change-me-*)
    stop 1 "Refusing: COMMAND_DB_PASSWORD is still a placeholder. The dashboard was not started."
    ;;
esac
if ! docker exec resto-postiz-postgres psql -U postiz -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='command'" | grep -q 1; then
  echo "The command database is missing on the existing Postiz Postgres. Creating it without recreating the container."
  sql_password="${command_password//\'/\'\'}"
  cat > "$tmp/command-role.sql" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'command') THEN
    CREATE ROLE command LOGIN PASSWORD '${sql_password}';
  END IF;
END
\$\$;
SQL
  docker exec -i resto-postiz-postgres psql -U postiz -d postiz -v ON_ERROR_STOP=1 < "$tmp/command-role.sql"
  rm -f "$tmp/command-role.sql"
  docker exec resto-postiz-postgres psql -U postiz -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE command OWNER command"
fi
if ! docker exec -e PGPASSWORD="$command_password" resto-postiz-postgres psql -U command -d command -tAc "SELECT 1" | grep -q 1; then
  echo "The command role could not read the command database. The password was not changed and resto-command was not started."
  require_kept_unchanged
  stop 1
fi
echo "The command database answered. resto-postgres was not contacted."
require_kept_unchanged

set +e
docker compose -f "$ROOT/compose.marketing.yml" --profile marketing up -d --no-deps --no-recreate command
compose_code=$?
set -e
require_kept_unchanged
if [ "$compose_code" -ne 0 ]; then
  echo "docker compose up failed with exit ${compose_code}."
  echo "This is a partial Phase 3 installation, not a preflight failure."
  stop 4
fi

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 5 "http://${want_bind}:8090/health" | grep -q '"status": "ok"'; then
    ready=1
    break
  fi
  sleep 3
done
if [ "$ready" -ne 1 ]; then
  echo "resto-command did not answer on ${want_bind}:8090. This is a partial installation."
  stop 4
fi
login_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${want_bind}:8090/api/me" || true)"
if [ "$login_code" != "401" ]; then
  echo "The dashboard answered /api/me with ${login_code}. An unsigned request must be rejected."
  stop 4
fi
require_kept_unchanged
echo "Dashboard is answering on http://${want_bind}:8090/. Mautic, Postiz, Temporal, and production containers were not recreated."
echo "Postiz container health is not the public API authentication test. Do not treat this start as that test."
"$ROOT/scripts/measure-marketing.sh" dashboard
echo "Public HTTPS was not started."
