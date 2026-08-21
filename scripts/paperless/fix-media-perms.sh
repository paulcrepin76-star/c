#!/usr/bin/env bash
# Paperless on Unraid runs as nobody:users (uid 99). The Survey Cafe archive
# tree was created as root, so consume fails when it needs a new year folder.
# Safe to re-run. Does not change the storage-path template or move files.
set -euo pipefail

MEDIA="${1:-/mnt/user/paperless-ngx/media/documents}"
for tree in originals archive; do
  dir="$MEDIA/$tree/Survey Cafe"
  if [[ -d "$dir" ]]; then
    chown -R nobody:users "$dir"
    find "$dir" -type d -exec chmod 775 {} +
    echo "Fixed $dir"
  fi
done
chmod 775 "$MEDIA" "$MEDIA/originals" "$MEDIA/archive" 2>/dev/null || true
