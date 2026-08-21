#!/usr/bin/env bash
# Split mixed Swift Paperless scans into one invoice per page and file them.
# Run on Unraid: ./scripts/paperless/file-swift-scans.sh
# Dry run:      ./scripts/paperless/file-swift-scans.sh --dry-run
set -euo pipefail

C="$(
  docker ps --format '{{.Names}}|{{.Image}}' |
  awk -F'|' 'tolower($2) ~ /paperless/ && tolower($1) ~ /webserver/ {print $1; exit}'
)"
C="${C:-paperless-ngx-webserver-1}"

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/file_swift_scans.py"

if [[ ! -f "$SCRIPT" ]]; then
  echo "ERROR: $SCRIPT not found"
  exit 1
fi

docker cp "$SCRIPT" "$C":/tmp/file_swift_scans.py
docker exec -i "$C" python3 /tmp/file_swift_scans.py "$@"
