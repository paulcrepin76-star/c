#!/usr/bin/env bash
# First-run helper. Safe to re-run: it never overwrites passwords in .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

hex() { openssl rand -hex "${1:-32}"; }

upsert_env() {
  local key="$1"
  local value="$2"
  if [ ! -f "$ROOT/.env" ]; then
    return
  fi
  if grep -q "^${key}=" "$ROOT/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ROOT/.env"
  else
    echo "${key}=${value}" >> "$ROOT/.env"
  fi
}

detect_container() {
  local needle="$1"
  local skip="$2"
  docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null |
    awk -F'|' -v needle="$needle" -v skip="$skip" '
      tolower($0) ~ needle && $1 != skip { print $1; exit }
    ' || true
}

detect_port() {
  local name="$1"
  local internal="$2"
  local fallback="$3"
  local port=""
  if [ -n "$name" ]; then
    port="$(docker port "$name" "$internal" 2>/dev/null | head -1 | sed -E 's/.*:([0-9]+)$/\1/' || true)"
  fi
  echo "${port:-$fallback}"
}

if [ -d /mnt/user ]; then
  APPDATA="${APPDATA:-/mnt/user/appdata/resto}"
  CONSUME_DIR="${CONSUME_DIR:-/mnt/user/documents/invoices-inbox}"
  HOST_HINT="$(hostname -s 2>/dev/null || echo TOWER)"
  if command -v tailscale >/dev/null 2>&1; then
    TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
    HOST_HINT="${TS_IP:-$HOST_HINT}"
  fi
  echo "Unraid detected. Data will live under ${APPDATA}"
else
  APPDATA="${APPDATA:-$ROOT/appdata}"
  CONSUME_DIR="${CONSUME_DIR:-$ROOT/appdata/invoices-inbox}"
  HOST_HINT="localhost"
  echo "Local machine detected. Data will live under ${APPDATA}"
fi

mkdir -p \
  "$APPDATA/postgres" \
  "$APPDATA/n8n" \
  "$APPDATA/metabase" \
  "$APPDATA/resto-core" \
  "$CONSUME_DIR"

EXISTING_PAPERLESS="$(detect_container paperless resto-paperless)"
EXISTING_MEALIE="$(detect_container mealie resto-mealie)"

PAPERLESS_PORT="8010"
MEALIE_PORT="9925"
COMPOSE_PROFILES_VALUE=""
PAPERLESS_BASE="http://host.docker.internal:8000"
MEALIE_BASE="http://host.docker.internal:9000"

if [ -n "${EXISTING_PAPERLESS:-}" ]; then
  PAPERLESS_PORT="$(detect_port "$EXISTING_PAPERLESS" 8000 8000)"
  PAPERLESS_BASE="http://host.docker.internal:${PAPERLESS_PORT}"
  echo "Found existing Paperless: ${EXISTING_PAPERLESS} (port ${PAPERLESS_PORT})"
else
  echo "No Paperless container detected. Using ${PAPERLESS_BASE}"
  echo "This stack will NOT install Paperless — keep the one you already have."
fi
docker rm -f resto-paperless >/dev/null 2>&1 || true

if [ -n "${EXISTING_MEALIE:-}" ]; then
  MEALIE_PORT="$(detect_port "$EXISTING_MEALIE" 9000 9000)"
  MEALIE_BASE="http://host.docker.internal:${MEALIE_PORT}"
  echo "Found existing Mealie: ${EXISTING_MEALIE} (port ${MEALIE_PORT})"
else
  echo "No Mealie container detected. Using ${MEALIE_BASE}"
  echo "This stack will NOT install Mealie — keep the one you already have."
fi
docker rm -f resto-mealie >/dev/null 2>&1 || true

if [ -f "$ROOT/.env" ]; then
  echo ".env already exists — keeping passwords, updating service URLs."
  upsert_env COMPOSE_PROFILES "$COMPOSE_PROFILES_VALUE"
  upsert_env PAPERLESS_BASE_URL "$PAPERLESS_BASE"
  upsert_env PAPERLESS_URL "http://${HOST_HINT}:${PAPERLESS_PORT}"
  upsert_env MEALIE_BASE_URL "$MEALIE_BASE"
  upsert_env MEALIE_URL "http://${HOST_HINT}:${MEALIE_PORT}"
else
  POSTGRES_PASSWORD="$(hex 16)"
  SECRET_KEY="$(hex 32)"
  N8N_ENCRYPTION_KEY="$(hex 32)"
  PAPERLESS_SECRET_KEY="$(hex 32)"
  RESTO_API_KEY="$(hex 16)"

  sed \
    -e "s|^APPDATA=.*|APPDATA=${APPDATA}|" \
    -e "s|^CONSUME_DIR=.*|CONSUME_DIR=${CONSUME_DIR}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" \
    -e "s|^N8N_ENCRYPTION_KEY=.*|N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}|" \
    -e "s|^PAPERLESS_SECRET_KEY=.*|PAPERLESS_SECRET_KEY=${PAPERLESS_SECRET_KEY}|" \
    -e "s|^RESTO_API_KEY=.*|RESTO_API_KEY=${RESTO_API_KEY}|" \
    -e "s|^COMPOSE_PROFILES=.*|COMPOSE_PROFILES=${COMPOSE_PROFILES_VALUE}|" \
    -e "s|^PAPERLESS_BASE_URL=.*|PAPERLESS_BASE_URL=${PAPERLESS_BASE}|" \
    -e "s|^MEALIE_BASE_URL=.*|MEALIE_BASE_URL=${MEALIE_BASE}|" \
    -e "s|192.168.1.10|${HOST_HINT}|g" \
    "$ROOT/.env.example" > "$ROOT/.env"
  upsert_env PAPERLESS_URL "http://${HOST_HINT}:${PAPERLESS_PORT}"
  upsert_env MEALIE_URL "http://${HOST_HINT}:${MEALIE_PORT}"
  echo "Wrote .env with random passwords. This file stays on the server, not in git."
fi

chmod 600 "$ROOT/.env" 2>/dev/null || true

cat <<EOF

This stack will start: resto-core, n8n, Metabase, Postgres
Skipped (already on Unraid): ${EXISTING_PAPERLESS:-} ${EXISTING_MEALIE:-}

Next:
  ./scripts/remote-up.sh

Then open:
  http://${HOST_HINT}:8088   wine cellar + costing
  http://${HOST_HINT}:${PAPERLESS_PORT}   Paperless
  http://${HOST_HINT}:${MEALIE_PORT}   Mealie
  http://${HOST_HINT}:5678   n8n
  http://${HOST_HINT}:3001   Metabase
EOF
