#!/usr/bin/env bash
# Run on Unraid as root. Wires Mylar3 grab clients from the house stack.
# Does not enable JDownloader. Does not start Comicarr. Does not touch manga.
# Does not send imp_move. Does not autowant the whole library.
# Mylar3 was removed. Do not reinstall unless asked.
set -euo pipefail

if [ "${MYLAR3_REINSTALL:-}" != "1" ]; then
  echo "Mylar3 was removed. Do not reinstall unless asked." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_SRC="$HERE/../docker/comics/compose.mylar3.yml"
CONFIG_HELPER="$HERE/mylar3_config.py"
DOWNLOAD_HELPER="$HERE/mylar3_downloads.py"
MYLAR=/mnt/user/appdata/mylar3
COMICS=/mnt/user/media/book/comics
DDL=/mnt/user/downloads/mylar3
SAB_COMPLETE=/mnt/user/downloads/complete/comics
WHATBOX_COMICS=/mnt/remotes/whatbox/Downloads/comics
SONARR_DB=/mnt/user/appdata/sonarr/sonarr.db
PROWLARR_DB=/mnt/user/appdata/prowlarr/prowlarr.db
PROWLARR_CFG=/mnt/user/appdata/prowlarr/config.xml
SAB_INI=/mnt/user/appdata/sabnzbd/sabnzbd.ini
UI_PORT=8090

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$COMPOSE_SRC" ] || [ ! -f "$CONFIG_HELPER" ] || [ ! -f "$DOWNLOAD_HELPER" ]; then
  echo "Missing download helpers in $HERE"
  exit 1
fi
if [ ! -f "$SONARR_DB" ] || [ ! -f "$PROWLARR_DB" ] || [ ! -f "$PROWLARR_CFG" ]; then
  echo "Sonarr or Prowlarr is missing."
  exit 1
fi
if docker inspect comicarr >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' comicarr)" = "true" ]; then
  echo "Stop Comicarr first."
  exit 1
fi

mkdir -p "$DDL" "$SAB_COMPLETE" "$WHATBOX_COMICS"
chown 99:100 "$DDL" "$SAB_COMPLETE" 2>/dev/null || true

if [ -f "$SAB_INI" ]; then
  sab_key="$(awk -F= '/^api_key *=/{gsub(/ /,"",$2); print $2; exit}' "$SAB_INI")"
  if [ -n "${sab_key:-}" ]; then
    curl -sS -o /tmp/sab-comics-cat.out -w "sab_category_http=%{http_code}\n" --max-time 15 \
      --get \
      --data-urlencode "mode=set_config" \
      --data-urlencode "section=categories" \
      --data-urlencode "keyword=comics" \
      --data-urlencode "dir=comics" \
      --data-urlencode "apikey=${sab_key}" \
      "http://127.0.0.1:8081/api" >/dev/null || true
    unset sab_key
  fi
fi

cp -a "$COMPOSE_SRC" "$MYLAR/compose.yml"
cp -a "$CONFIG_HELPER" "$MYLAR/mylar3_config.py"
cp -a "$DOWNLOAD_HELPER" "$MYLAR/mylar3_downloads.py"
chown 99:100 "$MYLAR/mylar3_config.py" "$MYLAR/mylar3_downloads.py"
chmod 0755 "$MYLAR/mylar3_downloads.py"

# Config files stay on the host. Do not pass them through the container.
python3 "$DOWNLOAD_HELPER" apply \
  --config "$MYLAR/mylar/config.ini" \
  --sonarr-db "$SONARR_DB" \
  --prowlarr-db "$PROWLARR_DB" \
  --prowlarr-config "$PROWLARR_CFG" \
  > /tmp/mylar3-downloads.json 2>/tmp/mylar3-downloads.err || {
  echo "host python3 missing; applying inside a throwaway container"
  # Copy dbs into mylar config dir with tight perms, apply, delete copies.
  umask 077
  cp -a "$SONARR_DB" "$MYLAR/.sonarr.db"
  cp -a "$PROWLARR_DB" "$MYLAR/.prowlarr.db"
  cp -a "$PROWLARR_CFG" "$MYLAR/.prowlarr.xml"
  chmod 600 "$MYLAR/.sonarr.db" "$MYLAR/.prowlarr.db" "$MYLAR/.prowlarr.xml"
  cd "$MYLAR"
  docker compose run --rm --no-deps --entrypoint python3 mylar3 \
    /config/mylar3_downloads.py apply \
    --config /config/mylar/config.ini \
    --sonarr-db /config/.sonarr.db \
    --prowlarr-db /config/.prowlarr.db \
    --prowlarr-config /config/.prowlarr.xml \
    > /tmp/mylar3-downloads.json
  rm -f "$MYLAR/.sonarr.db" "$MYLAR/.prowlarr.db" "$MYLAR/.prowlarr.xml"
}

if grep -q '^imp_move = True' "$MYLAR/mylar/config.ini"; then
  echo "imp_move is on. Refusing to restart."
  exit 1
fi
if grep -q '^imp_rename = True' "$MYLAR/mylar/config.ini"; then
  echo "imp_rename is on. Refusing to restart."
  exit 1
fi
if grep -q '^jd2_enable = True' "$MYLAR/mylar/config.ini"; then
  echo "JDownloader was enabled. Refusing to restart."
  exit 1
fi
if grep -q '^rename_files = True' "$MYLAR/mylar/config.ini"; then
  echo "rename_files is on. Refusing to restart."
  exit 1
fi

cd "$MYLAR"
docker compose up -d --remove-orphans

code=000
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${UI_PORT}/" || true)"
  case "$code" in
    200|301|302|303|307|308) break ;;
  esac
  sleep 2
done

# Resume the in-place library import. Do not send move/rename flags.
curl -sS -o /tmp/mylar3-massimport.out -w "massimport_http=%{http_code}\n" --max-time 60 \
  --get --data-urlencode "action=massimport" \
  "http://127.0.0.1:${UI_PORT}/markImports" || true

echo "mylar3_http=$code"
echo "mylar3_downloads=$(tr '\n' ' ' < /tmp/mylar3-downloads.json)"
echo "ddl=$DDL"
echo "sab_complete=$SAB_COMPLETE"
echo "whatbox_comics=$WHATBOX_COMICS"
echo "UI: http://100.116.48.120:${UI_PORT}"
echo "ComicVine is the catalog. GetComics DDL + SABnzbd + Whatbox qBittorrent grab files."
echo "JDownloader is off. Auto-want is off. Do not turn on Rename."
echo "Search one series to test. Do not Search + Want All."
if [ -d "$COMICS/.zzz_check" ] && [ -z "$(ls -A "$COMICS/.zzz_check" 2>/dev/null || true)" ]; then
  rmdir "$COMICS/.zzz_check"
fi
