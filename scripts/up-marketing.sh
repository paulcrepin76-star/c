#!/usr/bin/env bash
# Starts only containers named in scripts/marketing-names.sh.
# Does not load the resto compose file, and does not start, stop, or recreate existing services.
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

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"

echo "Approved run creates or starts these containers, and no others:"
printf '  %s\n' "${MARKETING_CONTAINERS[@]}"
echo
echo "It will not start, stop, or recreate:"
printf '  %s\n' "${PROTECTED_CONTAINERS[@]}"
echo
echo "Writes, only after MARKETING_APPROVED=1:"
echo "  missing marketing passwords in .env, values not printed"
echo "  directories under \${APPDATA}/mautic, postiz, temporal, command"
echo "  the Docker network named resto, only if it is missing, with no containers attached yet"
echo "  new marketing containers from compose.marketing.yml"
echo
echo "It does not load the resto compose file."
echo "It does not change vm.max_map_count, ZFS properties, or share settings."
echo

if [ "$DRY" -eq 1 ]; then
  echo "Dry run. Nothing was written or started."
  exit 0
fi

if [ "${MARKETING_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started. When you want this on the server, run:"
  echo "  MARKETING_APPROVED=1 ./scripts/up-marketing.sh"
  exit 3
fi

if [ ! -f "$ROOT/.env" ]; then
  echo "No .env yet. Run ./scripts/setup.sh first. Nothing was started."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

if [ "${BIND_ADDR:-127.0.0.1}" = "0.0.0.0" ]; then
  echo "Refusing: BIND_ADDR=0.0.0.0 would publish the dashboard, Mautic, and Postiz on every interface."
  echo "Use the Tailscale address, or leave BIND_ADDR unset so the ports stay on 127.0.0.1."
  exit 1
fi

"$ROOT/scripts/preflight-marketing.sh"

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
fill_marketing_secrets "$ROOT/.env"

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

bad=0
for key in MAUTIC_DB_PASSWORD MAUTIC_DB_ROOT_PASSWORD POSTIZ_DB_PASSWORD POSTIZ_JWT_SECRET TEMPORAL_DB_PASSWORD COMMAND_SECRET_KEY COMMAND_ADMIN_PASSWORD COMMAND_DB_PASSWORD; do
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
  "${APPDATA:-$ROOT/appdata}/postiz/postgres" \
  "${APPDATA:-$ROOT/appdata}/temporal/postgres" \
  "${APPDATA:-$ROOT/appdata}/temporal/elasticsearch" \
  "${APPDATA:-$ROOT/appdata}/command"

if [ "$(id -u)" -eq 0 ]; then
  chown -R 1000:1000 "${APPDATA:-$ROOT/appdata}/temporal/elasticsearch" || true
fi

if ! docker network inspect resto >/dev/null 2>&1; then
  echo "Creating an empty Docker network named resto. No existing container is attached or started."
  docker network create \
    --label com.docker.compose.network=resto \
    --label com.docker.compose.project=resto \
    resto
fi

snapshot() {
  local name
  for name in "${PROTECTED_CONTAINERS[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      docker inspect -f '{{.Name}} {{.Id}} {{.State.Status}}' "$name"
    else
      echo "$name absent"
    fi
  done
}

before="$(snapshot)"

compose() {
  docker compose -f "$ROOT/compose.marketing.yml" "$@"
}

compose --profile marketing up -d --no-recreate \
  mautic-mysql mautic mautic-cron mautic-worker \
  postiz-postgres marketing-db-init \
  postiz-redis \
  temporal-postgres temporal-elasticsearch temporal temporal-ui \
  postiz \
  command

after="$(snapshot)"
if [ "$before" != "$after" ]; then
  echo "An existing container changed identity or run state. That was not supposed to happen."
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 4
fi

echo
echo "Marketing containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | awk 'NR==1 || /resto-mautic|resto-postiz|resto-temporal|resto-command|resto-marketing/'
echo
echo "Dashboard: ${COMMAND_URL:-http://${BIND_ADDR:-127.0.0.1}:${COMMAND_PORT:-8090}}"
echo "Mautic:    ${MAUTIC_URL:-http://${BIND_ADDR:-127.0.0.1}:${MAUTIC_PORT:-8084}}"
echo "Postiz:    ${POSTIZ_URL:-http://${BIND_ADDR:-127.0.0.1}:${POSTIZ_PORT:-4007}}"
echo "Temporal UI stays on 127.0.0.1:${TEMPORAL_UI_PORT:-8085}."
echo "Create the Mautic admin and the Postiz user in those sites, then save API keys in the dashboard Settings."
echo "The public HTTPS edge is separate and was not started. See docs/MARKETING.md."
echo "This script passes --no-recreate, so a second run does not reload environment changes into an existing marketing container."
