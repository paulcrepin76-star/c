#!/usr/bin/env bash
# Stops and removes marketing containers only. Existing resto containers are inspected and left alone.
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

if [ "${MARKETING_ROLLBACK_APPROVED:-0}" != "1" ]; then
  echo "Nothing was stopped. An approved rollback removes only:"
  printf '  %s\n' "${MARKETING_CONTAINERS[@]}"
  echo "It does not remove:"
  printf '  %s\n' "${PROTECTED_CONTAINERS[@]}"
  echo "Data directories stay unless you also set MARKETING_ROLLBACK_DELETE_DATA=1."
  echo "Those directories are only:"
  printf '  ${APPDATA}/%s\n' "${MARKETING_DATA_DIRS[@]}"
  echo "  MARKETING_ROLLBACK_APPROVED=1 ./scripts/rollback-marketing.sh"
  exit 3
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Nothing was removed."
  exit 1
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

for name in "${MARKETING_CONTAINERS[@]}"; do
  protected=0
  for keep in "${PROTECTED_CONTAINERS[@]}"; do
    if [ "$keep" = "$name" ]; then
      protected=1
    fi
  done
  if [ "$protected" -eq 1 ]; then
    echo "Refusing to remove protected container ${name}."
    exit 1
  fi
  if docker inspect "$name" >/dev/null 2>&1; then
    docker rm -f "$name" >/dev/null
    echo "Removed ${name}"
  else
    echo "${name} was not present"
  fi
done

after="$(snapshot)"
if [ "$before" != "$after" ]; then
  echo "A protected container changed. Rollback should not have done that."
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 4
fi

if [ "${MARKETING_ROLLBACK_DELETE_DATA:-0}" = "1" ]; then
  APPDATA="${APPDATA:-$ROOT/appdata}"
  base="$(cd "$APPDATA" && pwd)"
  for dir in "${MARKETING_DATA_DIRS[@]}"; do
    case "$dir" in
      postgres|n8n|metabase|resto-core|paperless|mealie|redis|homeassistant|frigate|price-collector)
        echo "Refusing to delete ${dir}."
        exit 1
        ;;
    esac
    target="${base}/${dir}"
    case "$target" in
      "$base"/"$dir")
        if [ -d "$target" ]; then
          rm -rf "$target"
          echo "Deleted ${target}"
        fi
        ;;
      *)
        echo "Refusing odd path ${target}"
        exit 1
        ;;
    esac
  done
else
  echo "Data directories were kept. Take a backup before using MARKETING_ROLLBACK_DELETE_DATA=1."
fi

echo "Rollback finished. Protected containers were not removed."
