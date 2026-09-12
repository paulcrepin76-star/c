#!/usr/bin/env bash
# Run on Unraid as root. Does not move or rename comic/manga files.
# Walks imprint folders (DC Comics, dc rebirth, Shueisha, …) and points
# Comicarr at the real series folders inside them.
set -euo pipefail

CFG_HOST=/mnt/user/appdata/comicarr/config/comicarr/config.ini
HERE="$(cd "$(dirname "$0")" && pwd)"
INDEXER="$HERE/comicarr_index.py"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if ! docker inspect comicarr >/dev/null 2>&1; then
  echo "comicarr container is not installed."
  exit 1
fi
if [ ! -f "$INDEXER" ]; then
  echo "Missing $INDEXER"
  exit 1
fi

docker start comicarr >/dev/null 2>&1 || true
sleep 2

docker cp "$INDEXER" comicarr:/tmp/comicarr_index.py
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_index.py \
  --comics /comics --manga /manga

chown -R 99:100 /mnt/user/media/book/comics/.comicarr-scan /mnt/user/media/book/manga/.comicarr-scan 2>/dev/null || true
COMIC_COUNT="$(find /mnt/user/media/book/comics/.comicarr-scan -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
MANGA_COUNT="$(find /mnt/user/media/book/manga/.comicarr-scan -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"

if [ ! -f "$CFG_HOST" ]; then
  echo "config.ini not found at $CFG_HOST"
  exit 1
fi
cp -a "$CFG_HOST" "$CFG_HOST.bak.$(date +%F-%H%M%S)"

docker exec comicarr /opt/comicarr/.venv/bin/python - << 'PY'
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
# Seconds between ComicVine calls. The public cap is ~200/hour; 2s burns it.
put("CV", "cvapi_rate", "18")

with path.open("w") as fh:
    cfg.write(fh)
print("Updated", path)
PY

mkdir -p /mnt/user/downloads/inbox /mnt/user/downloads/complete
chown -R 99:100 /mnt/user/downloads/inbox /mnt/user/downloads/complete
if [ -f /mnt/user/appdata/comicarr/compose.yml ]; then
  cd /mnt/user/appdata/comicarr
  docker compose up -d
  docker compose restart
else
  docker restart comicarr
fi
sleep 3
echo
echo "Comic series indexed: $COMIC_COUNT"
echo "Manga series indexed: $MANGA_COUNT"
echo "Open http://100.116.48.120:8090 → Import → Scan both tiles."
echo "Tiles should show /comics/.comicarr-scan and /manga/.comicarr-scan."
echo "Files were not moved. Leave move/rename off."
