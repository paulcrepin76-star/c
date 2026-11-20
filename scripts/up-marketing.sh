#!/usr/bin/env bash
# Starts one marketing stage. Does not load the resto compose file.
# Does not start, stop, or recreate existing services.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DRY=0
STAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --stage)
      STAGE="${2:-}"
      shift
      ;;
    --stage=*) STAGE="${1#*=}" ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-names.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

case "$STAGE" in
  mautic)
    SERVICES=("${STAGE_MAUTIC_SERVICES[@]}")
    DIRS=("${STAGE_MAUTIC_DIRS[@]}")
    ;;
  postiz)
    SERVICES=("${STAGE_POSTIZ_SERVICES[@]}")
    DIRS=("${STAGE_POSTIZ_DIRS[@]}")
    ;;
  dashboard)
    SERVICES=("${STAGE_DASHBOARD_SERVICES[@]}")
    DIRS=("${STAGE_DASHBOARD_DIRS[@]}")
    ;;
  "")
    echo "Install in three stages. Nothing was started."
    echo "  1. MARKETING_APPROVED=1 ./scripts/up-marketing.sh --stage mautic"
    echo "     then ./scripts/measure-marketing.sh mautic"
    echo "  2. MARKETING_APPROVED=1 ./scripts/up-marketing.sh --stage postiz"
    echo "     then ./scripts/measure-marketing.sh postiz"
    echo "  3. MARKETING_APPROVED=1 ./scripts/up-marketing.sh --stage dashboard"
    echo "     then ./scripts/measure-marketing.sh dashboard"
    echo
    echo "Mautic services:"
    printf '  %s\n' "${STAGE_MAUTIC_SERVICES[@]}"
    echo "Postiz services:"
    printf '  %s\n' "${STAGE_POSTIZ_SERVICES[@]}"
    echo "Dashboard services:"
    printf '  %s\n' "${STAGE_DASHBOARD_SERVICES[@]}"
    echo
    echo "Every running container outside that list is snapshotted and left alone."
    echo "Source: /mnt/cache/projects/resto-marketing"
    echo "Data:   /mnt/cache/appdata/surveycafe-marketing"
    echo "The existing resto bridge is joined. A new bridge is not created."
    echo "Postiz stays stopped until MARKETING_POSTIZ_APPROVED=1 and vm.max_map_count=262144."
    echo "The public Caddy file is not started."
    if [ "$DRY" -eq 1 ]; then
      exit 0
    fi
    exit 3
    ;;
  *)
    echo "Unknown stage: $STAGE" >&2
    exit 1
    ;;
esac

echo "Stage ${STAGE} creates or starts only:"
printf '  %s\n' "${SERVICES[@]}"
echo
echo "Every other container is snapshotted and left alone, including Paperless, Mealie, n8n, Home Assistant, and Frigate."
echo
echo "Writes, only after MARKETING_APPROVED=1 and a passing preflight:"
echo "  missing marketing passwords in this checkout's .env, values not printed"
echo "  this stage's directories under /mnt/cache/appdata/surveycafe-marketing"
echo "  a private CPython under this checkout's .tools directory when the host has no python3"
echo
echo "It joins the existing resto network and does not create a bridge."
echo "It does not load the resto compose file."
echo "It leaves the production Git tree alone."
echo "It does not change vm.max_map_count, ZFS properties, or share settings."
echo "It passes --no-recreate, so an existing container keeps its current settings."
echo "The public Caddy edge is not started."
echo "It does not back up .env. After passwords are filled, encrypt that file with scripts/backup-marketing-env.sh."
echo

if [ "$DRY" -eq 1 ]; then
  echo "Dry run. Nothing was written or started."
  exit 0
fi

if [ "$STAGE" = "postiz" ] && [ "${MARKETING_POSTIZ_APPROVED:-0}" != "1" ]; then
  echo "Postiz stays stopped until MARKETING_POSTIZ_APPROVED=1. vm.max_map_count must be 262144 first. Nothing was started."
  exit 3
fi

if [ "$STAGE" = "dashboard" ] && [ "${MARKETING_DASHBOARD_APPROVED:-0}" != "1" ]; then
  echo "The dashboard stays stopped until MARKETING_DASHBOARD_APPROVED=1. Nothing was started."
  exit 3
fi

if [ "${MARKETING_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started."
  exit 3
fi

if [ ! -f "$ROOT/.env" ]; then
  echo "No .env in this checkout. Copy .env.example to .env here and set APPDATA. Do not run setup.sh. Nothing was started."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

if [ "${BIND_ADDR:-127.0.0.1}" = "0.0.0.0" ]; then
  echo "Refusing: BIND_ADDR=0.0.0.0 would publish this stage on every interface."
  echo "Set BIND_ADDR to the Tailscale address."
  exit 1
fi

appdata="${APPDATA:-}"
if [ -z "$appdata" ]; then
  echo "Refusing: APPDATA is unset. Set it to /mnt/cache/appdata/surveycafe-marketing. Nothing was started."
  exit 1
fi
marketing_require_separate_paths "$ROOT" "$appdata"

export MARKETING_STAGE="$STAGE"
export MARKETING_PYTHON_FETCH=1
"$ROOT/scripts/preflight-marketing.sh"

# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
fill_marketing_secrets "$ROOT/.env"
echo "Passwords are in this checkout's .env. Encrypt that file with scripts/backup-marketing-env.sh before relying on this stage."

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

for dir in "${DIRS[@]}"; do
  mkdir -p "${appdata}/${dir}"
done

if [ "$STAGE" = "postiz" ] && [ "$(id -u)" -eq 0 ]; then
  chown -R 1000:1000 "${appdata}/temporal/elasticsearch" || true
fi

if ! docker network inspect resto >/dev/null 2>&1; then
  echo "Refusing: the Docker network resto does not exist. This script will not create a bridge. Nothing was started."
  exit 1
fi
echo "Joining the existing Docker network resto."

before="$(marketing_snapshot_others)"

set +e
docker compose -f "$ROOT/compose.marketing.yml" --profile marketing up -d --no-recreate "${SERVICES[@]}"
compose_code=$?
set -e
if [ "$compose_code" -ne 0 ]; then
  echo "docker compose up failed with exit ${compose_code}."
  echo "This is a partial installation, not a preflight failure."
  exit 4
fi

after="$(marketing_snapshot_others)"
if [ "$before" != "$after" ]; then
  echo "An existing container changed identity or run state. That was not supposed to happen."
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 4
fi

echo
echo "Stage ${STAGE} containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | awk 'NR==1 || /resto-mautic|resto-postiz|resto-temporal|resto-command|resto-marketing/'
echo
"$ROOT/scripts/measure-marketing.sh" "$STAGE"
echo "The public HTTPS edge was not started."
