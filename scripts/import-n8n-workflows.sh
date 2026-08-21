#!/usr/bin/env bash
# Import Survey Cafe n8n workflows. Safe to re-run (n8n updates by name when possible).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_ID="$(
  docker exec resto-postgres psql -U resto -d n8n -tAc \
    "SELECT id FROM \"user\" WHERE email='surveycafedowntown@gmail.com' LIMIT 1;"
)"
USER_ID="${USER_ID:-6e5cd921-5d93-4a39-8fc5-569959b48edc}"

docker cp "$ROOT/n8n/workflows/." resto-n8n:/tmp/resto-workflows
docker exec resto-n8n n8n import:workflow --separate --input=/tmp/resto-workflows --userId="$USER_ID"
docker exec resto-n8n n8n list:workflow
echo
echo "Open http://100.116.48.120:5678"
echo "Add credentials named exactly:"
echo "  Square Access Token"
echo "  Mealie API"
echo "  Paperless Token"
echo "Then open Square sales → cellar, paste Location ID, toggle Active."
