#!/usr/bin/env bash
# Imports only the marketing workflows. Does not activate them and does not
# change the Square, Mealie, or Paperless workflows.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! docker inspect resto-n8n >/dev/null 2>&1; then
  echo "resto-n8n is not running. Nothing was imported."
  exit 1
fi

docker exec resto-n8n mkdir -p /tmp/marketing-workflows
docker cp "$ROOT/n8n/marketing/." resto-n8n:/tmp/marketing-workflows
docker exec resto-n8n n8n import:workflow --separate --input=/tmp/marketing-workflows
echo
echo "Imported marketing workflows. They stay inactive until you turn one on in n8n."
echo "They call http://command:8090 with the existing RESTO_API_KEY."
echo "Open the dashboard at http://100.116.48.120:8090"
