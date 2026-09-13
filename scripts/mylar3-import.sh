#!/usr/bin/env bash
# Run on Unraid as root. Imports existing /comics folders into Mylar3.
# Does not move or rename archives. Does not touch manga. Does not start Comicarr.
#
#   bash scripts/mylar3-import.sh              # full scan + stamp + massimport
#   bash scripts/mylar3-import.sh resume       # massimport whatever is queued
#   bash scripts/mylar3-import.sh remaining    # leftover folders, then massimport
#   bash scripts/mylar3-import.sh status
#
# Do not send imp_move=0. Mylar does bool("0") which is True and will rename.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HELPER="$HERE/mylar3_import.py"
CONFIG_HELPER="$HERE/mylar3_config.py"
MYLAR=/mnt/user/appdata/mylar3
COMICS=/mnt/user/media/book/comics
KAPOWARR_DB=/mnt/user/appdata/kapowarr/Kapowarr.db
MYLAR_DB="$MYLAR/mylar/mylar.db"
VOLUMES_JSON="$MYLAR/kapowarr-volumes.json"
UI_PORT=8090

MODE=scan
SCAN_PATH=/comics
case "${1:-}" in
  resume|remaining|status|scan)
    MODE="$1"
    SCAN_PATH="${2:-/comics}"
    ;;
  "")
    ;;
  *)
    SCAN_PATH="$1"
    ;;
esac

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
chown 99:100 "$MYLAR/mylar3_import.py" "$MYLAR/mylar3_config.py"

refresh_volumes() {
  if [ -f "$KAPOWARR_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 -json "$KAPOWARR_DB" \
      "SELECT comicvine_id, folder FROM volumes WHERE folder IS NOT NULL AND folder != '';" \
      > "$VOLUMES_JSON" || echo '[]' > "$VOLUMES_JSON"
  else
    echo '[]' > "$VOLUMES_JSON"
  fi
  chmod 600 "$VOLUMES_JSON"
  chown 99:100 "$VOLUMES_JSON"
}

wait_ui() {
  local code=000
  for _ in $(seq 1 60); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${UI_PORT}/" || true)"
    case "$code" in
      200|301|302|303|307|308) return 0 ;;
    esac
    sleep 2
  done
  echo "mylar3_http=$code"
  return 1
}

apply_safe_config() {
  cd "$MYLAR"
  docker compose stop mylar3
  docker compose run --rm --no-deps --entrypoint python3 mylar3 \
    /config/mylar3_config.py apply --config /config/mylar/config.ini --api-key-out /config/.api-key
  if grep -q '^imp_move = True' "$MYLAR/mylar/config.ini"; then
    echo "imp_move is on. Refusing to import."
    exit 1
  fi
  if grep -q '^imp_rename = True' "$MYLAR/mylar/config.ini"; then
    echo "imp_rename is on. Refusing to import."
    exit 1
  fi
  docker compose up -d --remove-orphans
  wait_ui
}

refuse_if_move_on() {
  if grep -q '^imp_move = True' "$MYLAR/mylar/config.ini"; then
    echo "imp_move is on. Refusing to import."
    exit 1
  fi
  if grep -q '^imp_rename = True' "$MYLAR/mylar/config.ini"; then
    echo "imp_rename is on. Refusing to import."
    exit 1
  fi
}

helper() {
  cd "$MYLAR"
  docker compose run --rm --no-deps --entrypoint python3 mylar3 \
    /config/mylar3_import.py "$@"
}

count_archives() {
  find "$COMICS" -type f \( -iname '*.cbz' -o -iname '*.cbr' -o -iname '*.cb7' -o -iname '*.cbt' \) | wc -l
}

massimport() {
  refuse_if_move_on
  curl -sS -o /tmp/mylar3-massimport.out -w "massimport_http=%{http_code}\n" --max-time 60 \
    --get --data-urlencode "action=massimport" \
    "http://127.0.0.1:${UI_PORT}/markImports" || true
}

watch_progress() {
  local before="$1"
  for _ in $(seq 1 720); do
    counts="$(sqlite3 "$MYLAR_DB" "SELECT Status||'='||COUNT(*) FROM importresults GROUP BY Status;" 2>/dev/null | tr '\n' ' ' || true)"
    comics="$(sqlite3 "$MYLAR_DB" "SELECT COUNT(*) FROM comics;" 2>/dev/null || echo lock)"
    echo "import_progress comics=$comics $counts"
    if echo "$counts" | grep -q "Imported=" && ! echo "$counts" | grep -q "Not Imported="; then
      break
    fi
    if docker logs mylar3 2>&1 | tail -30 | grep -qi "api limit"; then
      echo "comicvine_rate_limited=yes"
      break
    fi
    sleep 15
  done
  after="$(count_archives)"
  echo "archives_after=$after"
  echo "comics_on_watchlist=$(sqlite3 "$MYLAR_DB" "SELECT COUNT(*) FROM comics;")"
  sqlite3 "$MYLAR_DB" "SELECT Status, COUNT(*) FROM importresults GROUP BY Status;"
  echo "UI: http://100.116.48.120:${UI_PORT}"
  echo "Files stay in $COMICS. Do not turn on Rename or Move."
  if [ "$before" != "$after" ]; then
    echo "Archive count changed. Investigate before importing more."
    exit 1
  fi
}

print_status() {
  echo "imp_move=$(grep -E '^imp_move ' "$MYLAR/mylar/config.ini" || true)"
  echo "imp_rename=$(grep -E '^imp_rename ' "$MYLAR/mylar/config.ini" || true)"
  echo "imp_paths=$(grep -E '^imp_paths ' "$MYLAR/mylar/config.ini" || true)"
  echo "archives=$(count_archives)"
  helper status --db /config/mylar/mylar.db
}

if [ "$MODE" = "status" ]; then
  print_status
  exit 0
fi

if [ "$MODE" = "resume" ]; then
  before="$(count_archives)"
  echo "archives_before=$before"
  refuse_if_move_on
  wait_ui
  massimport
  watch_progress "$before"
  exit 0
fi

if [ "$MODE" = "remaining" ]; then
  before="$(count_archives)"
  echo "archives_before=$before"
  refresh_volumes
  refuse_if_move_on
  wait_ui
  remaining="$(helper seed-remaining --db /config/mylar/mylar.db --volumes-json /config/kapowarr-volumes.json --comics-root /comics)"
  echo "remaining=$remaining"
  massimport
  watch_progress "$before"
  exit 0
fi

refresh_volumes
cd "$MYLAR"
apply_safe_config

before="$(count_archives)"
echo "archives_before=$before"

scan_qs="$(helper scan-query --path "$SCAN_PATH")"
echo "scan_query=$scan_qs"

# CherryPy wants query args. Keep move/rename off and paths on.
# Do not send imp_move=0. Mylar does bool("0") which is True and will rename.
curl -sS -o /tmp/mylar3-scan.out -w "scan_http=%{http_code}\n" --max-time 3600 \
  --get \
  --data-urlencode "path=${SCAN_PATH}" \
  --data-urlencode "scan=1" \
  --data-urlencode "imp_paths=1" \
  --data-urlencode "forcescan=1" \
  "http://127.0.0.1:${UI_PORT}/comicScan" || true

apply_safe_config

status=""
for _ in $(seq 1 180); do
  status="$(curl -sS --max-time 8 "http://127.0.0.1:${UI_PORT}/Check_ImportStatus" || true)"
  echo "scan_status=$status"
  if [ "$status" = "Import completed." ] || [ "$status" = "Failure" ]; then
    break
  fi
  sleep 5
done

stamped="$(helper stamp --db /config/mylar/mylar.db --volumes-json /config/kapowarr-volumes.json)"
echo "stamped=$stamped"
# Filename-only parse groups would become thousands of fake series. Keep
# rows that already have a ComicVine ID (Kapowarr stamp or zip metadata).
sqlite3 "$MYLAR_DB" "DELETE FROM importresults WHERE ComicID IS NULL OR ComicID='' OR ComicID='None';"
echo "import_series=$(sqlite3 "$MYLAR_DB" "SELECT COUNT(DISTINCT ComicID) FROM importresults;")"

massimport
watch_progress "$before"
