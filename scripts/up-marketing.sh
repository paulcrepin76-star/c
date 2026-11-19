#!/usr/bin/env bash
# Starts Mautic, Postiz, and the Survey Café dashboard.
# Refuses to run until MARKETING_APPROVED=1. Never deletes existing containers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DRY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [ ! -f "$ROOT/.env" ]; then
  echo "No .env yet. Run ./scripts/setup.sh first. Nothing was started."
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
fill_marketing_secrets "$ROOT/.env"

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

bad=0
for key in MAUTIC_DB_PASSWORD MAUTIC_DB_ROOT_PASSWORD POSTIZ_DB_PASSWORD POSTIZ_JWT_SECRET TEMPORAL_DB_PASSWORD COMMAND_SECRET_KEY COMMAND_ADMIN_PASSWORD POSTGRES_PASSWORD; do
  value="$(grep -E "^${key}=" "$ROOT/.env" | head -1 | cut -d= -f2- || true)"
  case "$value" in
    ""|change-me|change-me-*)
      echo "Refusing: ${key} is still a placeholder."
      bad=1
      ;;
  esac
done
if [ "$bad" -ne 0 ]; then
  exit 1
fi

echo "This will start new containers only:"
echo "  resto-mautic, resto-mautic-cron, resto-mautic-worker, resto-mautic-mysql"
echo "  resto-postiz, resto-postiz-redis"
echo "  resto-temporal, resto-temporal-postgres, resto-temporal-elasticsearch, resto-temporal-ui"
echo "  resto-command, resto-marketing-db-init"
echo "It loads compose.yml so the new services can see the resto network."
echo "It does not delete n8n, resto-core, Paperless, Mealie, or their volumes."
echo

if [ "$DRY" -eq 1 ]; then
  echo "Dry run. Nothing was started."
  exit 0
fi

if [ "${MARKETING_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started. When you want this on the server, run:"
  echo "  MARKETING_APPROVED=1 ./scripts/up-marketing.sh"
  exit 3
fi

"$ROOT/scripts/preflight-marketing.sh"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Nothing was started."
  exit 1
fi

mkdir -p \
  "${APPDATA:-$ROOT/appdata}/mautic/mysql" \
  "${APPDATA:-$ROOT/appdata}/mautic/config" \
  "${APPDATA:-$ROOT/appdata}/mautic/logs" \
  "${APPDATA:-$ROOT/appdata}/mautic/media/files" \
  "${APPDATA:-$ROOT/appdata}/mautic/media/images" \
  "${APPDATA:-$ROOT/appdata}/postiz/config" \
  "${APPDATA:-$ROOT/appdata}/postiz/uploads" \
  "${APPDATA:-$ROOT/appdata}/postiz/redis" \
  "${APPDATA:-$ROOT/appdata}/temporal/postgres" \
  "${APPDATA:-$ROOT/appdata}/temporal/elasticsearch" \
  "${APPDATA:-$ROOT/appdata}/command"

if [ "$(id -u)" -eq 0 ]; then
  chown -R 1000:1000 "${APPDATA:-$ROOT/appdata}/temporal/elasticsearch" || true
fi

snapshot() {
  local name
  for name in resto-postgres resto-n8n resto-core resto-metabase resto-redis resto-paperless resto-mealie resto-homeassistant resto-frigate resto-price-collector resto-mosquitto; do
    if docker inspect "$name" >/dev/null 2>&1; then
      docker inspect -f '{{.Name}} {{.Id}}' "$name"
    else
      echo "$name absent"
    fi
  done
}

before="$(snapshot)"

compose() {
  docker compose -f "$ROOT/compose.yml" -f "$ROOT/compose.marketing.yml" "$@"
}

# Bring the existing database up if it is stopped. --no-recreate refuses to replace it.
compose up -d --no-recreate --no-deps postgres

compose --profile marketing up -d --build \
  marketing-db-init \
  mautic-mysql mautic mautic-cron mautic-worker \
  postiz-redis \
  temporal-postgres temporal-elasticsearch temporal temporal-ui \
  postiz \
  command

after="$(snapshot)"
if [ "$before" != "$after" ]; then
  echo "Existing containers changed identity. That was not supposed to happen."
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 4
fi

echo
echo "Marketing containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | awk 'NR==1 || /resto-mautic|resto-postiz|resto-temporal|resto-command|resto-marketing/'
echo
echo "Dashboard: ${COMMAND_URL:-http://127.0.0.1:8090}"
echo "Mautic:    ${MAUTIC_URL:-http://127.0.0.1:${MAUTIC_PORT:-8084}}"
echo "Postiz:    ${POSTIZ_URL:-http://127.0.0.1:${POSTIZ_PORT:-4007}}"
echo "Create the Mautic admin and the Postiz user in those sites, then save API keys in the dashboard Settings."
echo "Turn off Postiz registration after the first user: POSTIZ_DISABLE_REGISTRATION=true and run this script again."
