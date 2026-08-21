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

if [ -f "$ROOT/.env" ]; then
  echo ".env already exists — leaving your secrets alone."
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
    -e "s|192.168.1.10|${HOST_HINT}|g" \
    "$ROOT/.env.example" > "$ROOT/.env"
  echo "Wrote .env with random passwords. This file stays on the server, not in git."
fi

chmod 600 "$ROOT/.env" 2>/dev/null || true

cat <<EOF

Next:
  docker compose up -d --build

Then open:
  http://${HOST_HINT}:8088   wine cellar + costing
  http://${HOST_HINT}:8010   Paperless
  http://${HOST_HINT}:9925   Mealie
  http://${HOST_HINT}:5678   n8n
  http://${HOST_HINT}:3001   Metabase

Do not paste FPL / Sam's / Square / mailbox passwords into chat.
Create those accounts in Paperless (mail) and n8n (Square) in the browser on the server.

Drop any PDF you still download by hand into:
  ${CONSUME_DIR}
EOF
