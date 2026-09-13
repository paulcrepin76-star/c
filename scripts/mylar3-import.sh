#!/usr/bin/env bash
# Run on Unraid as root. Imports existing /comics folders into Mylar3.
# Does not move or rename archives. Does not touch manga. Does not start Comicarr.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HELPER="$HERE/mylar3_import.py"
CONFIG_HELPER="$HERE/mylar3_config.py"
MYLAR=/mnt/user/appdata/mylar3
COMICS=/mnt/user/media/book/comics
KAPOWARR_DB=/mnt/user/appdata/kapowarr/Kapowarr.db
MYLAR_DB="$MYLAR/mylar/mylar.db"
VOLUMES_JSON="$MYLAR/kapowarr-volumes.json"
SCAN_PATH="${1:-/comics}"
UI_PORT=8090

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$HELPER" ] || [ ! -f "$CONFIG_HELPER" ]; then
  echo "Missing import helpers in $HERE"
  exit 1
fi
if [ ! -d "$COMICS" ]; then
  echo "Comics folder not found at $COMICS"
  exit 1
fi
if ! docker inspect mylar3 >/dev/null 2>&1; then
  echo "mylar3 is not installed. Run scripts/mylar3-install.sh first."
  exit 1
fi
if docker inspect comicarr >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' comicarr)" = "true" ]; then
  echo "Stop Comicarr first."
  exit 1
fi

cp -a "$HELPER" "$MYLAR/mylar3_import.py"
cp -a "$CONFIG_HELPER" "$MYLAR/mylar3_config.py"

if [ -f "$KAPOWARR_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 -json "$KAPOWARR_DB" \
    "SELECT comicvine_id, folder FROM volumes WHERE folder IS NOT NULL AND folder != '';" \
    > "$VOLUMES_JSON" || echo '[]' > "$VOLUMES_JSON"
else
  echo '[]' > "$VOLUMES_JSON"
fi
chmod 600 "$VOLUMES_JSON"
chown 99:100 "$VOLUMES_JSON" "$MYLAR/mylar3_import.py" "$MYLAR/mylar3_config.py"

cd "$MYLAR"
docker compose stop mylar3
docker compose run --rm --no-deps --entrypoint python3 mylar3 \
  /config/mylar3_config.py apply --config /config/mylar/config.ini --api-key-out /config/.api-key
docker compose up -d --remove-orphans

code=000
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${UI_PORT}/" || true)"
  case "$code" in
    200|301|302|303|307|308) break ;;
  esac
  sleep 2
done

before="$(find "$COMICS" -type f \( -iname '*.cbz' -o -iname '*.cbr' -o -iname '*.cb7' -o -iname '*.cbt' \) | wc -l)"
echo "archives_before=$before"

scan_qs="$(docker compose run --rm --no-deps --entrypoint python3 mylar3 \
  /config/mylar3_import.py scan-query --path "$SCAN_PATH")"
echo "scan_query=$scan_qs"

# CherryPy wants query args. Keep move/rename off and paths on.
curl -sS -o /tmp/mylar3-scan.out -w "scan_http=%{http_code}\n" --max-time 3600 \
  --get \
  --data-urlencode "path=${SCAN_PATH}" \
  --data-urlencode "scan=1" \
  --data-urlencode "autoadd=0" \
  --data-urlencode "imp_move=0" \
  --data-urlencode "imp_paths=1" \
  --data-urlencode "imp_rename=0" \
  --data-urlencode "imp_metadata=0" \
  --data-urlencode "imp_seriesfolders=1" \
  --data-urlencode "forcescan=1" \
  "http://127.0.0.1:${UI_PORT}/comicScan" || true

status=""
for _ in $(seq 1 180); do
  status="$(curl -sS --max-time 8 "http://127.0.0.1:${UI_PORT}/Check_ImportStatus" || true)"
  echo "scan_status=$status"
  if [ "$status" = "Import completed." ] || [ "$status" = "Failure" ]; then
    break
  fi
  sleep 5
done

stamped="$(docker compose run --rm --no-deps --entrypoint python3 mylar3 \
  /config/mylar3_import.py stamp --db /config/mylar/mylar.db --volumes-json /config/kapowarr-volumes.json)"
echo "stamped=$stamped"

curl -sS -o /tmp/mylar3-massimport.out -w "massimport_http=%{http_code}\n" --max-time 60 \
  --get --data-urlencode "action=massimport" \
  "http://127.0.0.1:${UI_PORT}/markImports" || true

for _ in $(seq 1 720); do
  counts="$(sqlite3 "$MYLAR_DB" "SELECT Status||'='||COUNT(*) FROM importresults GROUP BY Status;" | tr '\n' ' ')"
  comics="$(sqlite3 "$MYLAR_DB" "SELECT COUNT(*) FROM comics;")"
  echo "import_progress comics=$comics $counts"
  if echo "$counts" | grep -q "Not Imported=" && ! echo "$counts" | grep -q "Not Imported=0"; then
    if docker logs mylar3 2>&1 | tail -20 | grep -qi "api limit"; then
      echo "comicvine_rate_limited=yes"
      break
    fi
  fi
  if ! echo "$counts" | grep -q "Not Imported="; then
    break
  fi
  # Still importing if Not Imported remains and lock is held.
  sleep 15
done

after="$(find "$COMICS" -type f \( -iname '*.cbz' -o -iname '*.cbr' -o -iname '*.cb7' -o -iname '*.cbt' \) | wc -l)"
echo "archives_after=$after"
echo "comics_on_watchlist=$(sqlite3 "$MYLAR_DB" "SELECT COUNT(*) FROM comics;")"
sqlite3 "$MYLAR_DB" "SELECT Status, COUNT(*) FROM importresults GROUP BY Status;"
echo "UI: http://100.116.48.120:${UI_PORT}"
echo "Files stay in $COMICS. Do not turn on Rename or Move."
if [ "$before" != "$after" ]; then
  echo "Archive count changed. Investigate before importing more."
  exit 1
fi
