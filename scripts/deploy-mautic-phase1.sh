#!/usr/bin/env bash
# Installs Mautic, its MySQL, the cron container, and the worker.
# Bootstraps a private CPython before the checks when the host has no python3.
# Stops before writing .env or starting a container when preflight fails.
# Does not start Postiz, Temporal, Elasticsearch, the dashboard, or public HTTPS.
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

ancestor_subnet="95aa65bc110b6baa8aec840d5f824f684b8f4d5f"
ancestor_stack="cc57ca5d18222ef51114f6937a60bc9ac6c163f1"
ancestor_approved="d82e03f39aaa74d34c59ea009d7a4b8fb15a170a"
ancestor_installer="e8f918406dd0b004e5d1c4ee64d4654ba4e03939"
want_data="/mnt/cache/appdata/surveycafe-marketing"
want_bind="100.116.48.120"
tmp=""

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

marketing_containers_exist() {
  local name
  command -v docker >/dev/null 2>&1 || return 1
  for name in "${MARKETING_CONTAINERS[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

if [ "${MARKETING_PHASE1_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started."
  echo "Mautic phase 1 installs only resto-mautic-mysql, resto-mautic, resto-mautic-cron, and resto-mautic-worker."
  echo "Set MARKETING_DEPLOY_COMMIT to the full 40-character SHA and check that commit out. A branch tip is not accepted."
  echo "  MARKETING_DEPLOY_COMMIT=<sha> MARKETING_PHASE1_APPROVED=1 ./scripts/deploy-mautic-phase1.sh"
  exit 3
fi

unset MARKETING_MEMORY_ACK MARKETING_LOAD_ACK
unset MARKETING_POSTIZ_APPROVED MARKETING_DASHBOARD_APPROVED MARKETING_PUBLIC_APPROVED
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
for needed in "$ancestor_subnet" "$ancestor_stack" "$ancestor_approved" "$ancestor_installer"; do
  if ! git -C "$ROOT" merge-base --is-ancestor "$needed" HEAD; then
    stop 1 "Refusing: HEAD ${head_commit} does not contain ${needed}. Nothing was started."
  fi
done
echo "Marketing source: ${ROOT}"
echo "Pinned deployment commit ${head_commit}."
echo "Reviewed installer commit ${ancestor_installer} is contained in this checkout."
echo "Approved Mautic commit ${ancestor_approved} is contained in this checkout."

if [ -n "${MARKETING_ENV_PASSPHRASE:-}" ]; then
  if [ "${#MARKETING_ENV_PASSPHRASE}" -lt 16 ]; then
    stop 6 "The backup passphrase was rejected. It must be at least 16 characters. Nothing was started."
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
fi

export MARKETING_PYTHON_FETCH=1
if ! py="$("$ROOT/scripts/ensure-private-python.sh" | tail -n 1)" || [ ! -x "$py" ]; then
  stop 1 "Private Python could not be prepared. No system package was installed. Nothing was started."
fi
echo "Private Python: ${py}"
case "$py" in
  "$ROOT/.tools/python/bin/python3")
    echo "Using the private CPython under .tools. No system package was installed."
    ;;
  *)
    echo "Using an already installed Python interpreter. No system package was installed."
    ;;
esac

if [ -z "$tmp" ]; then
  tmp="$(mktemp -d)"
fi
if [ -f "$ROOT/.env" ]; then
  work="$ROOT/.env"
  chmod 600 "$work"
else
  work="$tmp/.env"
  cp "$ROOT/.env.example" "$work"
  chmod 600 "$work"
fi

appdata="$(marketing_env_value "$work" APPDATA)"
bind="$(marketing_env_value "$work" BIND_ADDR)"
if [ "$appdata" != "$want_data" ]; then
  stop 1 "Refusing: APPDATA is ${appdata:-unset}. It must be ${want_data}. Nothing was started."
fi
if [ "$bind" != "$want_bind" ]; then
  stop 1 "Refusing: BIND_ADDR is ${bind:-unset}. It must be ${want_bind}. Nothing was started."
fi
marketing_require_separate_paths "$ROOT" "$appdata"

echo "Checking the env file, then RAM, CPU, Docker network, storage, and port 8084."
if ! "$ROOT/scripts/check-marketing-firstrun.sh"; then
  stop 2 "The first-run check failed. No container was started."
fi
if ! MARKETING_STAGE=mautic MARKETING_ENV_FILE="$work" "$ROOT/scripts/preflight-marketing.sh"; then
  echo "Preflight failed. No container was started."
  if [ ! -f "$ROOT/.env" ]; then
    echo "No marketing .env was installed."
  fi
  stop 2
fi

if [ ! -f "$ROOT/.env" ]; then
  cp "$work" "$ROOT/.env"
fi
chmod 600 "$ROOT/.env"
echo "Marketing .env mode $(stat -c '%a' "$ROOT/.env")."

set +e
MARKETING_APPROVED=1 MARKETING_PYTHON_FETCH=1 "$ROOT/scripts/up-marketing.sh" --stage mautic
up_code=$?
set -e
if [ "$up_code" -ne 0 ]; then
  echo "up-marketing.sh exited ${up_code}."
  if [ "$up_code" -eq 2 ] && ! marketing_containers_exist; then
    echo "Preflight failed. No container was started."
    stop 2
  fi
  if [ "$up_code" -eq 4 ] || marketing_containers_exist; then
    echo "This is a partial installation, not a preflight failure."
    stop 4
  fi
  echo "Refused before Docker. No container was started."
  stop 1
fi
chmod 600 "$ROOT/.env"

expected=(
  resto-mautic
  resto-mautic-cron
  resto-mautic-mysql
  resto-mautic-worker
)
for name in "${expected[@]}"; do
  if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    echo "Mautic phase 1 did not leave ${name} running."
    echo "This is a partial installation, not a preflight failure."
    stop 4
  fi
done
for name in "${MARKETING_CONTAINERS[@]}"; do
  case "$name" in
    resto-mautic|resto-mautic-cron|resto-mautic-mysql|resto-mautic-worker) continue ;;
  esac
  if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
    echo "${name} is running. That container is outside this approval."
    echo "This is a partial installation, not a preflight failure."
    stop 4
  fi
done

deadline=$((SECONDS + 240))
health="missing"
while [ "$SECONDS" -lt "$deadline" ]; do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' resto-mautic 2>/dev/null || echo missing)"
  if [ "$health" = "healthy" ]; then
    break
  fi
  sleep 5
done
echo "resto-mautic health: ${health}"
if [ "$health" != "healthy" ]; then
  echo "Mautic did not become healthy. This is a partial installation, not a preflight failure."
  stop 4
fi
if ! command -v curl >/dev/null 2>&1 || ! curl -fsS --max-time 20 "http://${want_bind}:8084/" -o /dev/null; then
  echo "Mautic did not answer on http://${want_bind}:8084/. This is a partial installation, not a preflight failure."
  stop 4
fi
echo "Mautic answered on http://${want_bind}:8084/."
docker port resto-mautic
"$ROOT/scripts/measure-marketing.sh" mautic

if [ -z "${MARKETING_ENV_PASSPHRASE:-}" ]; then
  echo "Installation succeeded. Mautic phase 1 is up."
  echo "The encrypted .env backup was not created because no passphrase was supplied."
  echo "This is not a failed installation."
  stop 5
fi

set +e
MARKETING_ENV_BACKUP_APPROVED=1 "$ROOT/scripts/backup-marketing-env.sh" >"$tmp/backup.out" 2>"$tmp/backup.err"
backup_code=$?
set -e
cat "$tmp/backup.out"
cat "$tmp/backup.err" >&2
if [ "$backup_code" -ne 0 ]; then
  echo "Installation succeeded. The encrypted backup could not be created."
  echo "This is not a failed installation."
  stop 7
fi
enc="$(awk -F': ' '/^Encrypted marketing \.env: / {print $2}' "$tmp/backup.out" | head -1)"
if [ -z "$enc" ] || [ ! -f "$enc" ]; then
  echo "Installation succeeded. The encrypted backup file was not found."
  echo "This is not a failed installation."
  stop 7
fi
if [ "$(stat -c '%a' "$enc")" != "600" ]; then
  echo "Installation succeeded. The encrypted backup is not mode 600."
  echo "This is not a failed installation."
  stop 7
fi
actual="$(sha256sum "$enc" | awk '{print $1}')"
expected="$(awk 'NF {print $1; exit}' "$enc.sha256")"
if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
  echo "Installation succeeded. The encrypted backup checksum does not match."
  echo "This is not a failed installation."
  stop 7
fi
echo "Encrypted backup verified: ${enc}"
echo "Mautic phase 1 finished. Postiz, Temporal, Elasticsearch, the dashboard, and public HTTPS were not started."
