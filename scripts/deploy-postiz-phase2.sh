#!/usr/bin/env bash
# Installs Postiz, its Postgres and Redis, Temporal, Elasticsearch, and Temporal UI.
# Backs up the working Mautic database and the marketing .env first.
# Does not recreate Mautic, create a Docker network, change vm.max_map_count, or start the dashboard.
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

ancestor_phase1="99b5b0dd3d54ba5752d710a84d53e7c02449c748"
ancestor_installer="e8f918406dd0b004e5d1c4ee64d4654ba4e03939"
ancestor_approved="d82e03f39aaa74d34c59ea009d7a4b8fb15a170a"
want_data="/mnt/cache/appdata/surveycafe-marketing"
want_bind="100.116.48.120"
tmp=""

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
  resto-mautic-mysql
  resto-mautic-cron
  resto-mautic-worker
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

phase2_exists() {
  local name
  command -v docker >/dev/null 2>&1 || return 1
  for name in "${PHASE2_CONTAINERS[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

mautic_ids() {
  local name
  for name in "${MAUTIC_CONTAINERS[@]}"; do
    docker inspect -f '{{.Name}} {{.Id}}' "$name" 2>/dev/null || echo "absent ${name}"
  done
}

require_mautic_unchanged() {
  local now
  now="$(mautic_ids)"
  if [ "$now" != "$mautic_before" ]; then
    echo "Mautic container identity changed. Phase 2 must not recreate Mautic."
    diff -u <(printf '%s\n' "$mautic_before") <(printf '%s\n' "$now") || true
    stop 4
  fi
}

if [ "${MARKETING_PHASE2_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started."
  echo "Phase 2 installs Postiz, Postiz Postgres, Redis, Temporal, Temporal Postgres, Elasticsearch, Temporal UI, and the database init container."
  echo "It does not recreate Mautic. It does not change vm.max_map_count."
  echo "Set MARKETING_DEPLOY_COMMIT to the full 40-character SHA and check that commit out."
  echo "  MARKETING_ENV_PASSPHRASE='...' MARKETING_DEPLOY_COMMIT=<sha> MARKETING_PHASE2_APPROVED=1 ./scripts/deploy-postiz-phase2.sh"
  exit 3
fi

unset MARKETING_MEMORY_ACK MARKETING_LOAD_ACK MARKETING_MAP_COUNT_APPROVED
unset MARKETING_DASHBOARD_APPROVED MARKETING_PUBLIC_APPROVED
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
for needed in "$ancestor_phase1" "$ancestor_installer" "$ancestor_approved"; do
  if ! git -C "$ROOT" merge-base --is-ancestor "$needed" HEAD; then
    stop 1 "Refusing: HEAD ${head_commit} does not contain ${needed}. Nothing was started."
  fi
done
echo "Marketing source: ${ROOT}"
echo "Pinned deployment commit ${head_commit}."
echo "Phase 1 installer ${ancestor_phase1} is contained in this checkout."
echo "Reviewed installer commit ${ancestor_installer} is contained in this checkout."

if [ -z "${MARKETING_ENV_PASSPHRASE:-}" ] || [ "${#MARKETING_ENV_PASSPHRASE}" -lt 16 ]; then
  stop 6 "The backup passphrase was rejected. Phase 2 requires it before any backup or container change. Nothing was started."
fi
case "$MARKETING_ENV_PASSPHRASE" in
  *[![:space:]]*) ;;
  *) stop 6 "The backup passphrase was rejected. Nothing was started." ;;
esac
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
rm -f "$tmp/sample" "$tmp/sample.enc" "$tmp/sample.out" "$tmp/openssl.err"
echo "Backup passphrase verified. It was not printed."

if [ ! -f "$ROOT/.env" ] || [ -L "$ROOT/.env" ]; then
  stop 1 "Refusing: the working marketing .env must already exist and must not be a symlink. Phase 2 does not copy .env.example over it. Nothing was started."
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
mautic_before="$(mautic_ids)"
for name in "${MAUTIC_CONTAINERS[@]}"; do
  if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    stop 1 "Refusing: ${name} is not running. Phase 2 does not install Mautic. Nothing was started."
  fi
done
if ! docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' resto-mautic 2>/dev/null | grep -qx healthy; then
  stop 1 "Refusing: resto-mautic is not healthy. Phase 2 does not recreate it. Nothing was started."
fi
for name in "${PHASE2_CONTAINERS[@]}"; do
  if docker inspect "$name" >/dev/null 2>&1; then
    stop 1 "Refusing: ${name} already exists. Phase 2 will not recreate it. Mautic was not changed."
  fi
done
echo "Mautic is healthy. Its containers will not be recreated."

stamp="$(date +%Y%m%d-%H%M%S)"
set +e
MARKETING_BACKUP_APPROVED=1 \
  MARKETING_BACKUP_REQUIRE_MAUTIC=1 \
  MARKETING_BACKUP_STAMP="phase2-${stamp}" \
  "$ROOT/scripts/backup-marketing.sh" >"$tmp/db.out" 2>"$tmp/db.err"
db_code=$?
set -e
cat "$tmp/db.out"
cat "$tmp/db.err" >&2
if [ "$db_code" -ne 0 ]; then
  echo "The Mautic database backup failed. Phase 2 was not started. Mautic was not recreated."
  stop 7
fi
db_dir="$(awk -F': ' '/^Backup directory: / {print $2}' "$tmp/db.out" | head -1)"
db_sql="${db_dir}/mautic.sql"
db_sum="${db_sql}.sha256"
if [ -z "$db_dir" ] || [ ! -f "$db_sql" ] || [ ! -s "$db_sql" ]; then
  echo "The Mautic database backup file is missing. Phase 2 was not started."
  stop 7
fi
if ! grep -q "Dump completed" "$db_sql"; then
  echo "The Mautic database backup is incomplete. Phase 2 was not started."
  stop 7
fi
db_actual="$(sha256sum "$db_sql" | awk '{print $1}')"
db_expected="$(awk 'NF {print $1; exit}' "$db_sum")"
if [ -z "$db_expected" ] || [ "$db_actual" != "$db_expected" ]; then
  echo "The Mautic database backup checksum does not match. Phase 2 was not started."
  stop 7
fi
if [ "$(stat -c '%a' "$db_sql")" != "600" ]; then
  echo "The Mautic database backup is not mode 600. Phase 2 was not started."
  stop 7
fi
echo "Verified Mautic database backup: ${db_sql}"

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

set +e
MARKETING_ENV_BACKUP_APPROVED=1 \
  MARKETING_ENV_BACKUP_STAMP="phase2-${stamp}-before" \
  "$ROOT/scripts/backup-marketing-env.sh" >"$tmp/env-before.out" 2>"$tmp/env-before.err"
env_before_code=$?
set -e
cat "$tmp/env-before.out"
cat "$tmp/env-before.err" >&2
if [ "$env_before_code" -ne 0 ] || ! env_before="$(verify_env_backup "$tmp/env-before.out")"; then
  echo "The encrypted configuration backup failed. Phase 2 was not started. Mautic was not recreated."
  stop 7
fi
echo "Verified encrypted configuration backup: ${env_before}"
echo "The original marketing .env was backed up before any configuration change."

chmod 600 "$ROOT/.env"
export MARKETING_PYTHON_FETCH=1
if ! py="$("$ROOT/scripts/ensure-private-python.sh" | tail -n 1)" || [ ! -x "$py" ]; then
  stop 1 "Private Python could not be prepared. No system package was installed. Nothing was started."
fi
echo "Private Python: ${py}"
proxy_state="$("$py" "$ROOT/scripts/fix-mautic-trusted-proxies.py" --check "$ROOT/.env")"
if [ "$proxy_state" = "valid" ]; then
  echo "MAUTIC_TRUSTED_PROXIES is already valid JSON. Mautic configuration was not modified."
else
  proxy_result="$("$py" "$ROOT/scripts/fix-mautic-trusted-proxies.py" "$ROOT/.env")"
  if [ "$proxy_result" != "corrected" ]; then
    stop 1 "Could not validate MAUTIC_TRUSTED_PROXIES. Mautic was not recreated."
  fi
  chmod 600 "$ROOT/.env"
  echo "Corrected MAUTIC_TRUSTED_PROXIES in .env to an empty JSON array after the original backup was verified."
  echo "The running Mautic containers were not recreated."
fi

fill_marketing_secrets "$ROOT/.env"
chmod 600 "$ROOT/.env"

set +e
MARKETING_ENV_BACKUP_APPROVED=1 \
  MARKETING_ENV_BACKUP_STAMP="phase2-${stamp}-after" \
  "$ROOT/scripts/backup-marketing-env.sh" >"$tmp/env-after.out" 2>"$tmp/env-after.err"
env_after_code=$?
set -e
cat "$tmp/env-after.out"
cat "$tmp/env-after.err" >&2
if [ "$env_after_code" -ne 0 ] || ! env_after="$(verify_env_backup "$tmp/env-after.out")"; then
  echo "The encrypted backup of the updated configuration failed. Phase 2 was not started. Mautic was not recreated."
  stop 7
fi
echo "Verified encrypted configuration backup after new Phase 2 secrets: ${env_after}"
require_mautic_unchanged

echo "Checking RAM, CPU, the resto network, storage, ports 4007 and 8085, and vm.max_map_count."
if ! MARKETING_STAGE=postiz MARKETING_ENV_FILE="$ROOT/.env" "$ROOT/scripts/preflight-marketing.sh"; then
  echo "Preflight failed. No Phase 2 container was started. Mautic was not recreated."
  echo "vm.max_map_count was not changed. scripts/map-count-unraid.sh prints the reversible change."
  require_mautic_unchanged
  stop 2
fi

set +e
MARKETING_APPROVED=1 MARKETING_POSTIZ_APPROVED=1 MARKETING_PYTHON_FETCH=1 \
  "$ROOT/scripts/up-marketing.sh" --stage postiz
up_code=$?
set -e
require_mautic_unchanged
if [ "$up_code" -ne 0 ]; then
  echo "up-marketing.sh exited ${up_code}."
  if [ "$up_code" -eq 2 ] && ! phase2_exists; then
    echo "Preflight failed. No Phase 2 container was started. Mautic was not recreated."
    stop 2
  fi
  if [ "$up_code" -eq 4 ] || phase2_exists; then
    echo "This is a partial Phase 2 installation, not a preflight failure. Mautic was not recreated."
    stop 4
  fi
  echo "Refused before Phase 2 Docker changes. Mautic was not recreated."
  stop 1
fi

healthy_or_stop() {
  local name="$1"
  local status
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || echo missing)"
  if [ "$status" != "healthy" ]; then
    echo "${name} health: ${status}"
    echo "This is a partial Phase 2 installation, not a preflight failure."
    stop 4
  fi
  echo "${name} health: healthy"
}

deadline=$((SECONDS + 480))
pending=1
while [ "$SECONDS" -lt "$deadline" ]; do
  pending=0
  for name in resto-postiz resto-postiz-postgres resto-postiz-redis resto-temporal resto-temporal-postgres resto-temporal-elasticsearch; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || echo missing)"
    if [ "$status" != "healthy" ]; then
      pending=1
    fi
  done
  if [ "$pending" -eq 0 ]; then
    break
  fi
  sleep 5
done
for name in resto-postiz resto-postiz-postgres resto-postiz-redis resto-temporal resto-temporal-postgres resto-temporal-elasticsearch; do
  healthy_or_stop "$name"
done
if ! docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' resto-marketing-db-init 2>/dev/null | grep -qx 'exited 0'; then
  echo "resto-marketing-db-init did not exit 0."
  echo "This is a partial Phase 2 installation, not a preflight failure."
  stop 4
fi
echo "resto-marketing-db-init exited 0."
if ! docker inspect -f '{{.State.Running}}' resto-temporal-ui 2>/dev/null | grep -qx true; then
  echo "resto-temporal-ui is not running."
  echo "This is a partial Phase 2 installation, not a preflight failure."
  stop 4
fi
for name in resto-command resto-marketing-edge; do
  if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    echo "${name} is running. That container is outside this approval."
    stop 4
  fi
done
if ! curl -fsS --max-time 20 "http://${want_bind}:4007/" -o /dev/null; then
  echo "Postiz did not answer on http://${want_bind}:4007/."
  echo "This is a partial Phase 2 installation, not a preflight failure."
  stop 4
fi
echo "Postiz answered on http://${want_bind}:4007/."
if ! curl -fsS --max-time 20 "http://127.0.0.1:8085/" -o /dev/null; then
  echo "Temporal UI did not answer on http://127.0.0.1:8085/."
  echo "This is a partial Phase 2 installation, not a preflight failure."
  stop 4
fi
echo "Temporal UI answered on http://127.0.0.1:8085/."
if ! docker exec resto-temporal-elasticsearch curl -fsS "http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=5s" >/dev/null; then
  echo "Elasticsearch did not report yellow or green health."
  stop 4
fi
echo "Elasticsearch cluster health is at least yellow."
if ! docker exec resto-postiz-redis redis-cli ping | grep -qx PONG; then
  echo "Redis did not answer PONG."
  stop 4
fi
echo "Redis answered PONG."
if ! docker exec resto-postiz-postgres pg_isready -U postiz -d postiz >/dev/null; then
  echo "Postiz Postgres is not ready."
  stop 4
fi
echo "Postiz Postgres is ready."
if ! docker exec resto-temporal-postgres pg_isready -U temporal >/dev/null; then
  echo "Temporal Postgres is not ready."
  stop 4
fi
echo "Temporal Postgres is ready."
if ! curl -fsS --max-time 20 "http://${want_bind}:8084/" -o /dev/null; then
  echo "Mautic did not answer on http://${want_bind}:8084/ after Phase 2."
  stop 4
fi
if ! docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' resto-mautic 2>/dev/null | grep -qx healthy; then
  echo "resto-mautic is no longer healthy."
  stop 4
fi
require_mautic_unchanged
echo "Mautic is still healthy on http://${want_bind}:8084/. Its containers were not recreated."
"$ROOT/scripts/measure-marketing.sh" postiz
echo "Phase 2 finished. The dashboard and public HTTPS were not started. vm.max_map_count was not changed."
echo "Mautic database backup: ${db_sql}"
echo "Encrypted configuration before new secrets: ${env_before}"
echo "Encrypted configuration after new secrets: ${env_after}"
