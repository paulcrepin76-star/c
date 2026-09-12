#!/usr/bin/env python3
"""Build Comicarr scan folders from imprint/series trees.

Comicarr's Import scan only treats first-level folders as series and
``os.walk`` does not follow directory symlinks. This indexer finds the
real series directories (folders that actually hold comic files) and
recreates them as real directories of file-level symlinks, named after
the series leaf so ComicVine / MangaDex can match them.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

YEAR_SUFFIX = re.compile(r"\s*\(\d{4}\)\s*$")

EXTS = {".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".epub", ".pdf"}
SOURCE_MARKER = ".source"
SCAN_DIR_NAME = ".comicarr-scan"


def is_comic_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in EXTS


def kids(path: Path) -> tuple[list[Path], list[Path]]:
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        entries = list(path.iterdir())
    except OSError:
        return dirs, files
    for item in entries:
        if item.name.startswith("."):
            continue
        try:
            if item.is_symlink():
                continue
            if item.is_dir():
                dirs.append(item)
            elif is_comic_file(item):
                files.append(item)
        except OSError:
            continue
    return dirs, files


def collect(path: Path, acc: list[Path] | None = None) -> list[Path]:
    """Return series folders under ``path``.

    A series is a folder that contains comic files and at most one
    subdirectory. Mixed imprint folders (files plus two or more
    subdirectories) recurse into the children and leave the loose files.
    Single-child wrappers unwrap. Empty trees are skipped.
    """
    if acc is None:
        acc = []
    dirs, files = kids(path)
    if files and len(dirs) <= 1:
        acc.append(path)
        return acc
    if files and len(dirs) >= 2:
        for child in dirs:
            collect(child, acc)
        return acc
    if not dirs:
        return acc
    if len(dirs) == 1:
        return collect(dirs[0], acc)
    for child in dirs:
        collect(child, acc)
    return acc


def series_label(src: Path, root: Path, used: set[str], strip_year: bool = False) -> str:
    leaf = src.name.strip() or "series"
    leaf = leaf.replace("/", "-").replace("\x00", "")
    if strip_year:
        stripped = YEAR_SUFFIX.sub("", leaf).strip()
        if stripped:
            leaf = stripped
    leaf = leaf[:180]
    label = leaf
    if label in used:
        parent = src.parent.name if src.parent != root else ""
        parent = parent.replace("/", "-").replace("\x00", "")
        if parent:
            label = f"{leaf} [{parent}]"[:180]
    n = 2
    while label in used:
        label = f"{leaf} ({n})"
        n += 1
    used.add(label)
    return label


def iter_comic_files(src: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        root = Path(dirpath)
        for filename in filenames:
            if filename.startswith("."):
                continue
            item = root / filename
            try:
                if item.is_symlink():
                    continue
                if is_comic_file(item):
                    found.append(item)
            except OSError:
                continue
    return found


def unique_link_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    candidate = f"{stem} ({n}){ext}"
    while candidate in used:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    used.add(candidate)
    return candidate


def link_series(src: Path, dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    count = 0
    for src_file in iter_comic_files(src):
        name = unique_link_name(src_file.name, used)
        link = dest / name
        link.symlink_to(Path(os.path.relpath(src_file, dest)))
        count += 1
    (dest / SOURCE_MARKER).write_text(str(src.resolve()) + "\n", encoding="utf-8")
    return count


def clear_scan(scan: Path) -> None:
    if not scan.exists():
        return
    for old in scan.iterdir():
        if old.is_symlink() or old.is_file():
            old.unlink()
        elif old.is_dir():
            shutil.rmtree(old)


def index_root(root: Path, scan: Path, strip_year: bool = False) -> dict:
    root = root.resolve()
    scan = scan.resolve() if scan.exists() else scan
    series = [
        path
        for path in collect(root)
        if path.resolve() != scan and scan not in path.resolve().parents
    ]
    clear_scan(scan)
    scan.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    created: list[dict] = []
    files = 0
    for src in series:
        label = series_label(src, root, used, strip_year=strip_year)
        dest = scan / label
        linked = link_series(src, dest)
        files += linked
        created.append({"label": label, "source": str(src), "files": linked})
    return {"series": len(created), "files": files, "items": created}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index real series folders for Comicarr Import")
    parser.add_argument("--comics", type=Path, default=Path("/comics"))
    parser.add_argument("--manga", type=Path, default=Path("/manga"))
    parser.add_argument("--comics-scan", type=Path, default=None)
    parser.add_argument("--manga-scan", type=Path, default=None)
    args = parser.parse_args(argv)

    comics_root = args.comics
    manga_root = args.manga
    comics_scan = args.comics_scan or (comics_root / SCAN_DIR_NAME)
    manga_scan = args.manga_scan or (manga_root / SCAN_DIR_NAME)

    comics = index_root(comics_root, comics_scan) if comics_root.is_dir() else {"series": 0, "files": 0}
    manga = (
        index_root(manga_root, manga_scan, strip_year=True) if manga_root.is_dir() else {"series": 0, "files": 0}
    )
    print(f"COMICS {comics['series']} series {comics['files']} files")
    print(f"MANGA {manga['series']} series {manga['files']} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
