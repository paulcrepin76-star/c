#!/usr/bin/env bash
# Run on Unraid as root. Copies the working seedbox qBittorrent profile
# from Sonarr into Comicarr and maps completed files the same way Sonarr does.
# Does not print passwords.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PATCH_SRC="$HERE/../docker/comics/patches/qbittorrent_client.py"
COMPOSE_SRC="$HERE/../docker/comics/compose.comicarr.yml"
LIVE=/mnt/user/appdata/comicarr
SONARR_DB=/mnt/user/appdata/sonarr/sonarr.db
SEEDBOX_DL=/mnt/remotes/whatbox/Downloads
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required."
  exit 1
fi
if [ ! -f "$SONARR_DB" ]; then
  echo "Sonarr database not found at $SONARR_DB"
  exit 1
fi
if [ ! -f "$PATCH_SRC" ] || [ ! -f "$COMPOSE_SRC" ]; then
  echo "Missing $PATCH_SRC or $COMPOSE_SRC"
  exit 1
fi

mkdir -p "$LIVE/patches" "$LIVE/manual-backups" "$LIVE/disabled-comics" "$SEEDBOX_DL/manga"
cp -a "$LIVE/compose.yml" "$LIVE/manual-backups/compose-before-qbit-$STAMP.yml" 2>/dev/null || true
cp -a "$LIVE/config/comicarr/config.ini" "$LIVE/manual-backups/config-before-qbit-$STAMP.ini"
cp -a "$PATCH_SRC" "$LIVE/patches/qbittorrent_client.py"
cp -a "$COMPOSE_SRC" "$LIVE/compose.yml"

SETTINGS="$(mktemp)"
trap 'rm -f "$SETTINGS"' EXIT
chmod 600 "$SETTINGS"
sqlite3 "$SONARR_DB" "SELECT Settings FROM DownloadClients WHERE Implementation='QBittorrent' LIMIT 1;" > "$SETTINGS"
if ! jq -e .host "$SETTINGS" >/dev/null; then
  echo "No qBittorrent client in Sonarr."
  exit 1
fi

HOST="$(jq -r .host "$SETTINGS")"
PORT="$(jq -r .port "$SETTINGS")"
SSL="$(jq -r .useSsl "$SETTINGS")"
USER="$(jq -r .username "$SETTINGS")"
PASS_LEN="$(jq -r '.password|length' "$SETTINGS")"
if [ "$SSL" = "true" ] && [ "$PORT" = "443" ]; then
  URL="https://${HOST}"
elif [ "$SSL" = "true" ]; then
  URL="https://${HOST}:${PORT}"
else
  URL="http://${HOST}:${PORT}"
fi
echo "Using Sonarr qBittorrent $URL user=$USER pass_len=$PASS_LEN"

docker start comicarr >/dev/null 2>&1 || true
docker cp "$SETTINGS" comicarr:/tmp/qbit-sonarr.json
docker cp "$HERE/comicarr_set_qbit.py" comicarr:/tmp/comicarr_set_qbit.py
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_set_qbit.py
docker exec comicarr rm -f /tmp/qbit-sonarr.json /tmp/comicarr_set_qbit.py

cd "$LIVE"
docker compose up -d
code=000
for _ in $(seq 1 40); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8090/ || true)"
  if [ "$code" = "200" ]; then
    break
  fi
  sleep 1
done
echo "comicarr_http=$code"
echo "Completed manga path: $SEEDBOX_DL/manga -> /home/deicide/Downloads/manga"
echo "Open a manga in http://100.116.48.120:8090 and use Interactive Search."
