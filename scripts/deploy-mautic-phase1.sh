#!/usr/bin/env bash
# Installs Mautic, its MySQL, the cron container, and the worker.
# Stops before creating the checkout .env or starting a container when preflight fails.
# Does not start Postiz, Temporal, Elasticsearch, the dashboard, or public HTTPS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
marketing_refuse_production "$ROOT"

approved_commit="d82e03f39aaa74d34c59ea009d7a4b8fb15a170a"
ancestor_subnet="95aa65bc110b6baa8aec840d5f824f684b8f4d5f"
ancestor_stack="cc57ca5d18222ef51114f6937a60bc9ac6c163f1"
want_data="/mnt/cache/appdata/surveycafe-marketing"
want_bind="100.116.48.120"

if [ "${MARKETING_PHASE1_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started."
  echo "Mautic phase 1 installs only resto-mautic-mysql, resto-mautic, resto-mautic-cron, and resto-mautic-worker."
  echo "It runs preflight first and stops if RAM, CPU, the resto network, storage, or port 8084 fails."
  echo "  MARKETING_PHASE1_APPROVED=1 ./scripts/deploy-mautic-phase1.sh"
  exit 3
fi

unset MARKETING_MEMORY_ACK MARKETING_LOAD_ACK
unset MARKETING_POSTIZ_APPROVED MARKETING_DASHBOARD_APPROVED MARKETING_PUBLIC_APPROVED
umask 077

if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Refusing: ${ROOT} is not a Git checkout. Nothing was started."
  exit 1
fi
head_commit="$(git -C "$ROOT" rev-parse HEAD)"
for needed in "$ancestor_subnet" "$ancestor_stack" "$approved_commit"; do
  if ! git -C "$ROOT" merge-base --is-ancestor "$needed" HEAD; then
    echo "Refusing: HEAD ${head_commit} does not contain ${needed}. Nothing was started."
    exit 1
  fi
done
echo "Marketing source: ${ROOT}"
echo "HEAD ${head_commit}"
echo "Approved Mautic commit ${approved_commit} is contained in this checkout."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
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
  echo "Refusing: APPDATA is ${appdata:-unset}. It must be ${want_data}. Nothing was started."
  exit 1
fi
if [ "$bind" != "$want_bind" ]; then
  echo "Refusing: BIND_ADDR is ${bind:-unset}. It must be ${want_bind}. Nothing was started."
  exit 1
fi
marketing_require_separate_paths "$ROOT" "$appdata"

echo "Checking the env file, then RAM, CPU, Docker network, storage, and port 8084."
"$ROOT/scripts/check-marketing-firstrun.sh"
if ! MARKETING_STAGE=mautic MARKETING_ENV_FILE="$work" "$ROOT/scripts/preflight-marketing.sh"; then
  echo "Preflight failed. No container was started."
  if [ ! -f "$ROOT/.env" ]; then
    echo "No marketing .env was installed."
  fi
  exit 1
fi

if [ ! -f "$ROOT/.env" ]; then
  cp "$work" "$ROOT/.env"
fi
chmod 600 "$ROOT/.env"
echo "Marketing .env mode $(stat -c '%a' "$ROOT/.env")."

running_names() {
  docker ps --format '{{.Names}}' | LC_ALL=C sort
}
before="$(running_names)"

MARKETING_APPROVED=1 "$ROOT/scripts/up-marketing.sh" --stage mautic
chmod 600 "$ROOT/.env"

after="$(running_names)"
expected=(
  resto-mautic
  resto-mautic-cron
  resto-mautic-mysql
  resto-mautic-worker
)
for name in "${expected[@]}"; do
  if ! printf '%s\n' "$after" | grep -qx "$name"; then
    echo "Mautic phase 1 did not leave ${name} running."
    exit 1
  fi
done
for name in "${MARKETING_CONTAINERS[@]}"; do
  case "$name" in
    resto-mautic|resto-mautic-cron|resto-mautic-mysql|resto-mautic-worker) continue ;;
  esac
  if printf '%s\n' "$after" | grep -qx "$name" && ! printf '%s\n' "$before" | grep -qx "$name"; then
    echo "${name} started during Mautic phase 1. That container is outside this approval."
    exit 1
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
  echo "Mautic did not become healthy. No further stage was started."
  exit 1
fi
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS --max-time 20 "http://${want_bind}:8084/" -o /dev/null; then
    echo "Mautic is healthy inside Docker but http://${want_bind}:8084/ did not answer."
    exit 1
  fi
  echo "Mautic answered on http://${want_bind}:8084/."
else
  echo "curl is not installed. The Tailscale port was not opened from this shell."
  exit 1
fi
docker port resto-mautic
"$ROOT/scripts/measure-marketing.sh" mautic

if [ -z "${MARKETING_ENV_PASSPHRASE:-}" ]; then
  echo "Mautic phase 1 is up. The encrypted .env backup was not created."
  echo "Export MARKETING_ENV_PASSPHRASE in this shell and run ./scripts/backup-marketing-env.sh."
  echo "The passphrase is not written on the server."
  exit 5
fi
MARKETING_ENV_BACKUP_APPROVED=1 "$ROOT/scripts/backup-marketing-env.sh"
echo "Mautic phase 1 finished. Postiz, the dashboard, and public HTTPS were not started."
