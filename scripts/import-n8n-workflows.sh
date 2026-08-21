#!/usr/bin/env bash
# Import Survey Cafe n8n workflows. Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_ID="$(
  docker exec resto-postgres psql -U resto -d n8n -tAc \
    "SELECT id FROM \"user\" WHERE email='surveycafedowntown@gmail.com' LIMIT 1;"
)"
USER_ID="${USER_ID:-6e5cd921-5d93-4a39-8fc5-569959b48edc}"

docker cp "$ROOT/n8n/workflows/." resto-n8n:/tmp/resto-workflows
if docker exec resto-n8n n8n import:workflow --help 2>/dev/null | grep -q overwrite; then
  docker exec resto-n8n n8n import:workflow --separate --overwrite --input=/tmp/resto-workflows --userId="$USER_ID"
else
  docker exec resto-n8n n8n import:workflow --separate --input=/tmp/resto-workflows --userId="$USER_ID"
fi
docker exec resto-n8n n8n list:workflow || true

# Activate the nightly sync. Logins live on resto-core /connect, not here.
docker exec resto-postgres psql -U resto -d n8n -c \
  "UPDATE workflow_entity SET active = false WHERE name IN ('Mealie recipes → cellar', 'Paperless invoices → cellar');" || true
docker exec resto-postgres psql -U resto -d n8n -c \
  "UPDATE workflow_entity SET active = true WHERE name = 'Square sales → cellar';" || true

echo
echo "Open http://100.116.48.120:8088/connect and log in to Square, Mealie, Paperless."
echo "You do not add n8n credentials."
