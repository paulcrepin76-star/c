#!/usr/bin/env bash
# Run on Unraid as root after scripts/comicarr-fix-libraries.sh.
# Starts Comicarr and Kapowarr library imports. Does not rename files.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily)."
  exit 1
fi

docker cp "$HERE/comicarr_import.py" comicarr:/tmp/comicarr_import.py
docker cp "$HERE/comicarr_index.py" kapowarr:/tmp/comicarr_index.py
docker cp "$HERE/kapowarr_import.py" kapowarr:/tmp/kapowarr_import.py

mkdir -p /mnt/user/appdata/comicarr/logs /mnt/user/appdata/kapowarr
touch /mnt/user/appdata/comicarr/logs/library-import.log
touch /mnt/user/appdata/kapowarr/library-import.log

echo "Starting Comicarr import (then Kapowarr). Do not run both against ComicVine at once."
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_import.py
echo "Comicarr import finished. Starting Kapowarr..."
docker exec kapowarr python3 /tmp/kapowarr_import.py
echo "Done."
echo "  docker exec comicarr cat /tmp/comicarr-import-summary.json"
echo "  docker exec kapowarr cat /tmp/kapowarr-import-summary.json"
