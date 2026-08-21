#!/usr/bin/env bash
# First-run helper. Safe to re-run: it never overwrites an existing .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

hex() { openssl rand -hex "${1:-32}"; }

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
  "$APPDATA/paperless/data" \
  "$APPDATA/paperless/media" \
  "$APPDATA/paperless/export" \
  "$APPDATA/mealie" \
  "$APPDATA/n8n" \
  "$APPDATA/metabase" \
  "$APPDATA/resto-core" \
  "$CONSUME_DIR"

EXISTING_PAPERLESS="$(
  docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null |
  awk -F'|' 'tolower($0) ~ /paperless/ {print $1; exit}' || true
)"
PAPERLESS_PORT="8000"
if [ -n "${EXISTING_PAPERLESS:-}" ]; then
  DETECTED_PORT="$(docker port "$EXISTING_PAPERLESS" 8000 2>/dev/null | head -1 | sed -E 's/.*:([0-9]+)$/\1/' || true)"
  PAPERLESS_PORT="${DETECTED_PORT:-8000}"
  echo "Found existing Paperless container: ${EXISTING_PAPERLESS} (port ${PAPERLESS_PORT})"
  echo "Will NOT start a second Paperless."
fi

if [ -f "$ROOT/.env" ]; then
  echo ".env already exists — leaving your secrets alone."
else
  POSTGRES_PASSWORD="$(hex 16)"
  SECRET_KEY="$(hex 32)"
  N8N_ENCRYPTION_KEY="$(hex 32)"
  PAPERLESS_SECRET_KEY="$(hex 32)"
  RESTO_API_KEY="$(hex 16)"
  COMPOSE_PROFILES_VALUE=""
  PAPERLESS_BASE="http://paperless:8000"
  if [ -n "${EXISTING_PAPERLESS:-}" ]; then
    PAPERLESS_BASE="http://host.docker.internal:${PAPERLESS_PORT}"
  else
    COMPOSE_PROFILES_VALUE="paperless"
    PAPERLESS_PORT="8010"
    PAPERLESS_BASE="http://paperless:8000"
  fi

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
    -e "s|192.168.1.10|${HOST_HINT}|g" \
    -e "s|:8010|:${PAPERLESS_PORT}|g" \
    "$ROOT/.env.example" > "$ROOT/.env"
  echo "Wrote .env with random passwords. This file stays on the server, not in git."
fi

chmod 600 "$ROOT/.env" 2>/dev/null || true

cat <<EOF

Next:
  ./scripts/remote-up.sh

Then open:
  http://${HOST_HINT}:8088   wine cellar + costing
  http://${HOST_HINT}:${PAPERLESS_PORT}   Paperless (existing)
  http://${HOST_HINT}:9925   Mealie
  http://${HOST_HINT}:5678   n8n
  http://${HOST_HINT}:3001   Metabase

Paperless Gmail import stays as it is. This install does not replace it.
EOF
