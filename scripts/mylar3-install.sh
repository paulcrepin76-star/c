#!/usr/bin/env bash
# Run on Unraid as root. Starts Mylar3 next to Kapowarr.
# Does not move, rename, or import the comic library Kavita will read.
# Does not start Comicarr. Does not stop Kapowarr or Rensaio.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_SRC="$HERE/../docker/comics/compose.mylar3.yml"
HELPER="$HERE/mylar3_config.py"
MYLAR=/mnt/user/appdata/mylar3
DOWNLOADS=/mnt/user/downloads/mylar3
COMICS=/mnt/user/media/book/comics
KAPOWARR_DB=/mnt/user/appdata/kapowarr/Kapowarr.db
CV_FILE="$MYLAR/.cv.key"
API_FILE="$MYLAR/.api-key"
UI_PORT=8090

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$COMPOSE_SRC" ]; then
  echo "Missing $COMPOSE_SRC"
  exit 1
fi
if [ ! -f "$HELPER" ]; then
  echo "Missing $HELPER"
  exit 1
fi
if [ ! -d "$COMICS" ]; then
  echo "Comics folder not found at $COMICS"
  exit 1
fi
if docker inspect comicarr >/dev/null 2>&1; then
  echo "Comicarr is still present. Leave it stopped; this script will not start it."
  if [ "$(docker inspect -f '{{.State.Running}}' comicarr 2>/dev/null || echo false)" = "true" ]; then
    echo "Stop Comicarr first so it cannot fight Mylar3 for port $UI_PORT."
    exit 1
  fi
fi

if ss -lnt 2>/dev/null | grep -q ":${UI_PORT} " && ! docker inspect -f '{{.State.Running}}' mylar3 2>/dev/null | grep -q true; then
  echo "Host port $UI_PORT is already in use. Free it before installing Mylar3."
  exit 1
fi

mkdir -p "$MYLAR" "$DOWNLOADS"
cp -a "$COMPOSE_SRC" "$MYLAR/compose.yml"
cp -a "$HELPER" "$MYLAR/mylar3_config.py"
chown -R 99:100 "$MYLAR" "$DOWNLOADS"
chmod 0755 "$MYLAR/mylar3_config.py"

if [ -f "$KAPOWARR_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  umask 077
  sqlite3 "$KAPOWARR_DB" "SELECT value FROM config WHERE key='comicvine_api_key';" > "$CV_FILE"
  chmod 600 "$CV_FILE"
  chown 99:100 "$CV_FILE"
  if [ ! -s "$CV_FILE" ]; then
    echo "Kapowarr ComicVine key was empty; Mylar3 will start without one."
    rm -f "$CV_FILE"
  else
    echo "copied_comicvine_from_kapowarr=yes"
  fi
else
  echo "Kapowarr database not found; Mylar3 will start without a ComicVine key."
fi

cd "$MYLAR"
docker compose pull
docker compose up -d --remove-orphans

ini=""
for _ in $(seq 1 90); do
  if [ -f "$MYLAR/mylar/config.ini" ]; then
    ini="$MYLAR/mylar/config.ini"
    break
  fi
  sleep 2
done
if [ -z "$ini" ]; then
  echo "Mylar3 did not write config.ini"
  docker compose logs --tail 80 || true
  exit 1
fi

docker compose stop mylar3

apply_args=(apply --config /config/mylar/config.ini --api-key-out /config/.api-key)
if [ -s "$CV_FILE" ]; then
  apply_args+=(--comicvine-file /config/.cv.key)
fi

docker compose run --rm --no-deps --entrypoint python3 mylar3 \
  /config/mylar3_config.py "${apply_args[@]}"

rm -f "$CV_FILE"
chmod 600 "$API_FILE" 2>/dev/null || true
chown 99:100 "$API_FILE" 2>/dev/null || true

docker compose up -d --remove-orphans

code=000
for _ in $(seq 1 90); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${UI_PORT}/" || true)"
  case "$code" in
    200|301|302|303|307|308) break ;;
  esac
  sleep 2
done

summary="$(docker compose run --rm --no-deps --entrypoint python3 mylar3 \
  /config/mylar3_config.py summary --config /config/mylar/config.ini)"

echo "mylar3_http=$code"
echo "mylar3_summary=$summary"
echo "UI: http://100.116.48.120:${UI_PORT}"
echo "Comics path: $COMICS -> /comics"
echo "Downloads: $DOWNLOADS -> /downloads"
echo "Kapowarr stays on http://100.116.48.120:5656"
echo "Do not use Manage / Import / Rename on folders Kavita already reads."
if [ -d "$COMICS/.zzz_check" ] && [ -z "$(ls -A "$COMICS/.zzz_check" 2>/dev/null || true)" ]; then
  rmdir "$COMICS/.zzz_check"
  echo "removed_empty_mylar_write_test=yes"
fi
case "$code" in
  200|301|302|303|307|308) ;;
  *)
    echo "Mylar3 UI did not answer yet. Check: docker logs mylar3"
    exit 1
    ;;
esac
