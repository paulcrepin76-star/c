#!/usr/bin/env bash
# Run on Unraid as root. Does not move or rename comic/manga files.
# Walks imprint folders (DC Comics, dc rebirth, Shueisha, …) and points
# Comicarr at the real series folders inside them.
set -euo pipefail

CFG_HOST=/mnt/user/appdata/comicarr/config/comicarr/config.ini

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if ! docker inspect comicarr >/dev/null 2>&1; then
  echo "comicarr container is not installed."
  exit 1
fi

docker start comicarr >/dev/null 2>&1 || true
sleep 2

docker exec -i comicarr python3 - << 'PY'
from pathlib import Path
import os

EXTS = {".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".epub", ".pdf"}


def kids(path: Path):
    dirs, files = [], []
    try:
        entries = list(path.iterdir())
    except OSError:
        return dirs, files
    for item in entries:
        if item.name.startswith("."):
            continue
        if item.is_dir() and not item.is_symlink():
            dirs.append(item)
        elif item.is_file() and item.suffix.lower() in EXTS:
            files.append(item)
    return dirs, files


def collect(path: Path, acc: list) -> None:
    dirs, files = kids(path)
    if files and len(dirs) <= 1:
        acc.append(path)
        return
    if files and len(dirs) >= 2:
        for child in dirs:
            collect(child, acc)
        return
    if not dirs:
        return
    if len(dirs) == 1:
        collect(dirs[0], acc)
        return
    for child in dirs:
        collect(child, acc)


def index_root(root: Path, scan: Path) -> list:
    if scan.exists():
        for old in scan.iterdir():
            old.unlink()
    scan.mkdir(parents=True, exist_ok=True)
    series: list[Path] = []
    collect(root, series)
    series = [path for path in series if scan not in path.parents and path != scan]
    created = []
    for src in series:
        label = " - ".join(src.relative_to(root).parts)[:180]
        dest = scan / label
        n = 2
        while dest.exists():
            dest = scan / f"{label} ({n})"
            n += 1
        dest.symlink_to(Path(os.path.relpath(src, dest.parent)))
        created.append(label)
    return created


comics = index_root(Path("/comics"), Path("/comics/.comicarr-scan"))
manga = index_root(Path("/manga"), Path("/manga/.comicarr-scan"))
print(f"COMICS {len(comics)}")
print(f"MANGA {len(manga)}")
PY

chown -R 99:100 /mnt/user/media/book/comics/.comicarr-scan /mnt/user/media/book/manga/.comicarr-scan 2>/dev/null || true
COMIC_COUNT="$(find /mnt/user/media/book/comics/.comicarr-scan -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
MANGA_COUNT="$(find /mnt/user/media/book/manga/.comicarr-scan -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"

if [ ! -f "$CFG_HOST" ]; then
  echo "config.ini not found at $CFG_HOST"
  exit 1
fi
cp -a "$CFG_HOST" "$CFG_HOST.bak.$(date +%F-%H%M%S)"

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
sleep 3
echo
echo "Comic series indexed: $COMIC_COUNT"
echo "Manga series indexed: $MANGA_COUNT"
echo "Open http://100.116.48.120:8090 → Import → Scan both tiles."
echo "Tiles should show /comics/.comicarr-scan and /manga/.comicarr-scan."
echo "Files were not moved. Leave move/rename off."
