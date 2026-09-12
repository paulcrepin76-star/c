#!/usr/bin/env bash
# Run on Unraid as root. Makes Comicarr search the five main manga series
# (Bleach, MPD Psycho, Naruto, One Piece, Shangri-La Frontier) and find
# them on MangaDex / Prowlarr. Does not print API keys.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/comicarr_enable_manga_search.py"
LIVE=/mnt/user/appdata/comicarr
PROWLARR_CFG=/mnt/user/appdata/prowlarr/config.xml

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$SCRIPT" ]; then
  echo "Missing $SCRIPT"
  exit 1
fi

mkdir -p "/mnt/user/media/book/manga/Naruto (1999)"
docker start comicarr >/dev/null 2>&1 || true
docker cp "$SCRIPT" comicarr:/tmp/comicarr_enable_manga_search.py
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_enable_manga_search.py "$@"
docker exec comicarr rm -f /tmp/comicarr_enable_manga_search.py

if [ ! -f "$PROWLARR_CFG" ]; then
  echo "prowlarr_search skipped (no config)"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "prowlarr_search skipped (no jq)"
  exit 0
fi

KEY="$(sed -n 's/.*<ApiKey>\(.*\)<\/ApiKey>.*/\1/p' "$PROWLARR_CFG")"
if [ -z "$KEY" ]; then
  echo "prowlarr_search skipped (no key)"
  exit 0
fi

echo "prowlarr_search"
for q in "Bleach" "MPD Psycho" "Naruto" "One Piece" "Shangri-La Frontier"; do
  count="$(
    curl -sS --max-time 90 -H "X-Api-Key: ${KEY}" --get \
      "http://127.0.0.1:9696/api/v1/search" \
      --data-urlencode "query=${q}" \
      --data-urlencode "limit=20" \
      | jq 'if type=="array" then length else (.|length) end' \
      || echo 0
  )"
  echo "  ${q}: ${count}"
done
unset KEY
