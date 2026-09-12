#!/usr/bin/env bash
# Run on Unraid as root. Does not move or rename comic/manga files.
# Builds a series-level scan index and points Comicarr at it.
set -euo pipefail

COMICS_HOST="${COMICS_HOST:-/mnt/user/media/book/comics}"
MANGA_HOST="${MANGA_HOST:-/mnt/user/media/book/manga}"
COMICS_SCAN="$COMICS_HOST/.comicarr-scan"
MANGA_SCAN="$MANGA_HOST/.comicarr-scan"
CFG_HOST=/mnt/user/appdata/comicarr/config/comicarr/config.ini

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if ! docker inspect comicarr >/dev/null 2>&1; then
  echo "comicarr container is not installed."
  exit 1
fi

is_comic() {
  case "${1##*.}" in
    cbz|cbr|cb7|cbt|zip|rar|7z|epub|pdf|CBZ|CBR|EPUB|PDF) return 0 ;;
    *) return 1 ;;
  esac
}

count_here() {
  local dir="$1" files=0 dirs=0
  local e
  shopt -s nullglob
  for e in "$dir"/*; do
    [ -e "$e" ] || continue
    local base
    base="$(basename "$e")"
    [ "$base" = ".comicarr-scan" ] && continue
    if [ -d "$e" ] && [ ! -L "$e" ]; then
      dirs=$((dirs + 1))
    elif [ -f "$e" ] && is_comic "$base"; then
      files=$((files + 1))
    fi
  done
  echo "$dirs $files"
}

looks_like_issue_folder() {
  echo "$1" | grep -Eq '^[0-9#]|^(Issue|Chapter|Ch\.?|Vol\.?)[[:space:]]*[0-9]'
}

# Publisher/imprint folder = named series children, not Issue 001 / Chapter 12.
is_bucket() {
  local dir="$1"
  local counts dirs files
  counts="$(count_here "$dir")"
  dirs="${counts%% *}"
  files="${counts##* }"
  [ "$dirs" -ge 2 ] || return 1
  [ "$files" -le 15 ] || return 1
  local issue_like=0 child
  shopt -s nullglob
  for child in "$dir"/*; do
    [ -d "$child" ] || continue
    looks_like_issue_folder "$(basename "$child")" && issue_like=$((issue_like + 1))
  done
  [ "$issue_like" -lt $((dirs / 2)) ]
}

link_series() {
  local scan_root="$1" source_dir="$2" label="$3"
  local dest="$scan_root/$label"
  dest="${dest//\/\//\/}"
  mkdir -p "$(dirname "$dest")"
  local rel
  rel="$(realpath --relative-to="$(dirname "$dest")" "$source_dir")"
  ln -sfn "$rel" "$dest"
}

index_tree() {
  local host_root="$1" scan_root="$2"
  rm -rf "$scan_root"
  mkdir -p "$scan_root"
  local top
  shopt -s nullglob
  for top in "$host_root"/*; do
    [ -d "$top" ] || continue
    [ -L "$top" ] && continue
    local name
    name="$(basename "$top")"
    [ "$name" = ".comicarr-scan" ] && continue
    if is_bucket "$top"; then
      local child
      for child in "$top"/*; do
        [ -d "$child" ] || continue
        [ -L "$child" ] && continue
        local child_name
        child_name="$(basename "$child")"
        [ "$child_name" = ".comicarr-scan" ] && continue
        link_series "$scan_root" "$child" "$name - $child_name"
      done
    else
      link_series "$scan_root" "$top" "$name"
    fi
  done
}

echo "=== COMICS TOP LEVEL ==="
ls -1 "$COMICS_HOST" 2>/dev/null || echo "(missing) $COMICS_HOST"
echo
echo "=== MANGA TOP LEVEL ==="
ls -1 "$MANGA_HOST" 2>/dev/null || echo "(missing) $MANGA_HOST"
echo

index_tree "$COMICS_HOST" "$COMICS_SCAN"
index_tree "$MANGA_HOST" "$MANGA_SCAN"
chown -R 99:100 "$COMICS_SCAN" "$MANGA_SCAN" 2>/dev/null || true

COMIC_COUNT="$(find "$COMICS_SCAN" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
MANGA_COUNT="$(find "$MANGA_SCAN" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"

echo "Indexed $COMIC_COUNT comic series under $COMICS_SCAN"
echo "Indexed $MANGA_COUNT manga series under $MANGA_SCAN"
echo "Sample comics:"
ls -1 "$COMICS_SCAN" | head
echo "Sample manga:"
ls -1 "$MANGA_SCAN" | head
echo

if [ ! -f "$CFG_HOST" ]; then
  echo "config.ini not found at $CFG_HOST"
  find /mnt/user/appdata/comicarr -name config.ini || true
  exit 1
fi
cp -a "$CFG_HOST" "$CFG_HOST.bak.$(date +%F-%H%M%S)"

docker start comicarr >/dev/null 2>&1 || true
sleep 2

docker exec -i comicarr python3 - << 'PY'
from configparser import ConfigParser
from pathlib import Path

path = Path("/config/comicarr/config.ini")
cfg = ConfigParser()
cfg.optionxform = str
cfg.read(path)

def put(section, key, value):
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)

put("General", "destination_dir", "/comics")
put("General", "manga_destination_dir", "/manga")
put("Import", "comic_dir", "/comics/.comicarr-scan")
put("Import", "manga_dir", "/manga/.comicarr-scan")
put("Import", "add_comics", "True")
put("Import", "imp_move", "False")
put("Import", "imp_rename", "False")
put("Import", "imp_paths", "True")
put("Import", "imp_metadata", "True")
put("Import", "imp_seriesfolders", "True")
put("Import", "import_dir", "/downloads/inbox")
put("PostProcess", "enable_check_folder", "True")
put("PostProcess", "check_folder", "/downloads/complete")
put("Update", "newcom_dir", "/downloads/complete")
put("MangaDex", "mangadex_enabled", "True")

with path.open("w") as fh:
    cfg.write(fh)
print("Updated", path)
PY

mkdir -p /mnt/user/downloads/inbox /mnt/user/downloads/complete
chown -R 99:100 /mnt/user/downloads/inbox /mnt/user/downloads/complete

cd /mnt/user/appdata/comicarr
docker compose up -d
docker compose restart
sleep 4
docker ps --filter name=comicarr --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo
echo "Scan tiles should now say:"
echo "  Comic library  /comics/.comicarr-scan   ($COMIC_COUNT series)"
echo "  Manga library  /manga/.comicarr-scan    ($MANGA_COUNT series)"
echo
echo "Open http://100.116.48.120:8090 → Import → Scan both tiles."
echo "Files were not moved. Leave move/rename off."
echo "Comics still need a ComicVine API key or rows stay No match."
