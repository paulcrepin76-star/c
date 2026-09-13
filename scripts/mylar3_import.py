#!/usr/bin/env python3
"""Import existing /comics folders into Mylar3 without moving files.

Scan in place (imp_paths=1; never send imp_move/imp_rename), stamp ComicVine
IDs from Kapowarr when a folder has exactly one volume, then mass-import.
A later remaining pass seeds leftover English series folders as one group
each so filename fragments are not added as fake series.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

COMIC_ROOT = "/comics"
HOST_COMICS = "/mnt/user/media/book/comics"
IMPRINT_ROOTS = {
    "/comics",
    "/comics/dc new 52",
    "/comics/dc rebirth",
    "/comics/absolute dc",
    "/comics/marvel",
    "/comics/spider-man",
    "/comics/amazing spiderman",
}
MANGA_MARKERS = ("/manga/", "/series/")
ARCHIVE_SUFFIXES = (".cbz", ".cbr", ".cb7", ".cbt")
SKIP_PATH_MARKERS = (
    "complete english comic collection",
    "marvel now! previews",
    "marvel intégrale",
    "marvel integrale",
    "/.zzz_check",
)
SKIP_TREES = {
    "ecc ediciones",
    "ediciones zinco",
    "editorial muchnik",
    "editorial novaro",
    "panini uk",
    "panini verlag",
    "pika édition",
    "pika edition",
    "sage - sagédition",
    "sage - sagedition",
    "urban comics",
    "marvel integral",
    "omnibus downloads",
}
NESTED_ACCIDENTS = {
    "/comics/dc comics/absolute superman (2025)/absolute batman",
}
TREE_YEAR = {
    "dc new 52": "2011",
    "dc rebirth": "2016",
}
YEAR_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)\s*$")
NAME_NOISE_RE = re.compile(r"[^a-z0-9]+")


def folder_key(path: str) -> str:
    return str(path or "").rstrip("/").lower()


def is_imprint_root(path: str) -> bool:
    return folder_key(path) in IMPRINT_ROOTS


def is_manga_path(path: str) -> bool:
    lowered = folder_key(path)
    return any(marker in lowered for marker in MANGA_MARKERS)


def parent_dir(path: str) -> str:
    return str(Path(path).parent).rstrip("/")


def container_path(path: str) -> str:
    text = str(path or "").rstrip("/")
    host = HOST_COMICS.rstrip("/")
    if folder_key(text).startswith(folder_key(host)):
        text = COMIC_ROOT + text[len(host) :]
    if not text:
        return COMIC_ROOT
    return text


def tree_name(path: str) -> str:
    parts = folder_key(container_path(path)).split("/")
    if len(parts) >= 3:
        return parts[2]
    return ""


def basename_key(path: str) -> str:
    name = Path(container_path(path)).name
    name = YEAR_RE.sub(r"\g<name>", name)
    return NAME_NOISE_RE.sub("", name.lower())


def parse_folder_name(path: str) -> tuple[str, str | None]:
    name = Path(container_path(path)).name.strip()
    match = YEAR_RE.match(name)
    if match:
        return match.group("name").strip(), match.group("year")
    year = TREE_YEAR.get(tree_name(path))
    return name, year


def skip_folder(path: str) -> bool:
    folder = container_path(path)
    key = folder_key(folder)
    if is_imprint_root(folder) or is_manga_path(folder):
        return True
    if key in NESTED_ACCIDENTS:
        return True
    if any(marker in key for marker in SKIP_PATH_MARKERS):
        return True
    if tree_name(folder) in SKIP_TREES:
        return True
    if not folder_key(folder).startswith(folder_key(COMIC_ROOT)):
        return True
    return False


def scan_query(path: str) -> dict[str, str]:
    if is_manga_path(path):
        raise ValueError("refusing to scan a manga path")
    if not folder_key(path).startswith(COMIC_ROOT):
        raise ValueError("scan path must stay under /comics")
    # CherryPy does bool(imp_move). bool("0") is True, so never send
    # imp_move=0 / imp_rename=0 / imp_metadata=0 as query strings.
    return {
        "path": path,
        "scan": "1",
        "imp_paths": "1",
        "forcescan": "1",
    }


def unique_folder_volumes(volumes: list[dict]) -> dict[str, dict]:
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for volume in volumes:
        folder = str(volume.get("folder") or "").rstrip("/")
        if not folder or is_imprint_root(folder) or is_manga_path(folder):
            continue
        if not volume.get("comicvine_id"):
            continue
        by_folder[folder_key(folder)].append(volume)
    chosen: dict[str, dict] = {}
    for items in by_folder.values():
        if len(items) != 1:
            continue
        folder = str(items[0]["folder"]).rstrip("/")
        chosen[folder] = items[0]
    return chosen


def stamp_updates(volumes: list[dict]) -> list[tuple[str, str]]:
    """Return (comicvine_id, folder_prefix) pairs safe to stamp."""
    updates: list[tuple[str, str]] = []
    for folder, volume in unique_folder_volumes(volumes).items():
        updates.append((str(int(volume["comicvine_id"])), folder.rstrip("/") + "/"))
    return updates


def apply_stamps(conn: sqlite3.Connection, updates: list[tuple[str, str]]) -> int:
    changed = 0
    for comic_id, prefix in updates:
        cur = conn.execute(
            """
            UPDATE importresults
               SET ComicID = ?
             WHERE Status = 'Not Imported'
               AND ComicLocation LIKE ?
               AND (ComicID IS NULL OR ComicID = '' OR ComicID = 'None')
            """,
            (comic_id, prefix + "%"),
        )
        changed += int(cur.rowcount or 0)
    conn.commit()
    return changed


def collapse_stamped_groups(conn: sqlite3.Connection) -> int:
    """One massimport group per stamped ComicVine ID."""
    cur = conn.execute(
        """
        UPDATE importresults
           SET DynamicName = ComicID,
               Volume = NULL
         WHERE Status = 'Not Imported'
           AND ComicID IS NOT NULL
           AND ComicID != ''
           AND ComicID != 'None'
        """
    )
    conn.commit()
    return int(cur.rowcount or 0)


def snapshot_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in ARCHIVE_SUFFIXES:
            paths.append(str(path.relative_to(root)))
    return paths


def snapshot_changed(before: list[str], after: list[str]) -> dict:
    before_set = set(before)
    after_set = set(after)
    return {
        "before": len(before),
        "after": len(after),
        "added": sorted(after_set - before_set)[:20],
        "removed": sorted(before_set - after_set)[:20],
        "unchanged": before_set == after_set,
    }


def series_folders(root: Path) -> list[str]:
    folders: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in ARCHIVE_SUFFIXES:
            folders.add(container_path(str(path.parent)))
    return sorted(folders, key=folder_key)


def claimed_parents(conn: sqlite3.Connection) -> set[str]:
    claimed: set[str] = set()
    for (location,) in conn.execute("SELECT ComicLocation FROM comics"):
        if location:
            claimed.add(folder_key(container_path(str(location))))
    for (location,) in conn.execute("SELECT ComicLocation FROM importresults"):
        if location:
            claimed.add(folder_key(parent_dir(container_path(str(location)))))
    return claimed


def used_comic_ids(conn: sqlite3.Connection) -> set[str]:
    used: set[str] = set()
    for table, column in (("comics", "ComicID"), ("importresults", "ComicID")):
        for (comic_id,) in conn.execute(f"SELECT {column} FROM {table}"):
            text = str(comic_id or "").strip()
            if text and text != "None":
                used.add(text)
    return used


def claimed_basenames(paths: set[str]) -> set[str]:
    names = {basename_key(path) for path in paths}
    names.discard("")
    return names


def best_shared_volume(folder: str, volumes: list[dict]) -> dict | None:
    items = [
        volume
        for volume in volumes
        if folder_key(str(volume.get("folder") or "")) == folder_key(folder)
        and volume.get("comicvine_id")
    ]
    if len(items) <= 1:
        return items[0] if items else None
    folder_base = basename_key(folder)
    matches = []
    for volume in items:
        name = basename_key(str(volume.get("folder") or folder))
        if name and name == folder_base:
            matches.append(volume)
    if len(matches) == 1:
        return matches[0]
    return None


def _imp_id(conn: sqlite3.Connection) -> str:
    while True:
        candidate = str(random.randint(10_000_000, 99_999_999))
        row = conn.execute("SELECT 1 FROM importresults WHERE impID=?", (candidate,)).fetchone()
        if row is None:
            return candidate


def archive_files(root: Path, folder: str) -> list[Path]:
    path = Path(folder)
    if not path.is_absolute() or folder_key(folder).startswith(folder_key(COMIC_ROOT)):
        rel = container_path(folder)
        if rel == COMIC_ROOT:
            path = root
        else:
            path = root.joinpath(*Path(rel).parts[1:])
    if not path.is_dir():
        return []
    files = [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and item.suffix.lower() in ARCHIVE_SUFFIXES
    ]
    return files


def seed_folder_rows(
    conn: sqlite3.Connection,
    folder: str,
    files: list[Path],
    *,
    comic_id: str | None,
    comic_name: str,
    comic_year: str | None,
) -> int:
    if not files:
        return 0
    dynamic = str(int(comic_id)) if comic_id else f"folder:{folder_key(folder)}"
    inserted = 0
    for item in files:
        location = f"{container_path(folder).rstrip('/')}/{item.name}"
        conn.execute(
            """
            INSERT INTO importresults (
                impID, ComicName, ComicYear, Status, ImportDate, ComicFilename,
                ComicLocation, WatchMatch, DisplayName, SRID, ComicID, IssueID,
                Volume, IssueNumber, DynamicName, IssueCount, implog
            ) VALUES (?, ?, ?, 'Not Imported', date('now'), ?, ?, NULL, ?, NULL, ?, NULL, NULL, NULL, ?, NULL, NULL)
            """,
            (
                _imp_id(conn),
                comic_name,
                comic_year,
                item.name,
                location,
                comic_name,
                str(int(comic_id)) if comic_id else None,
                dynamic,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def unique_by_tree_name(volumes: list[dict]) -> dict[tuple[str, str], dict]:
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for folder, volume in unique_folder_volumes(volumes).items():
        key = (tree_name(folder), basename_key(folder))
        if key[1]:
            buckets[key].append(volume)
    return {key: items[0] for key, items in buckets.items() if len(items) == 1}


def remaining_plan(
    folders: list[str],
    volumes: list[dict],
    claimed: set[str],
    used_ids: set[str],
) -> list[dict]:
    unique = {folder_key(folder): volume for folder, volume in unique_folder_volumes(volumes).items()}
    unique_names = unique_by_tree_name(volumes)
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for volume in volumes:
        folder = str(volume.get("folder") or "").rstrip("/")
        if folder and volume.get("comicvine_id"):
            by_folder[folder_key(folder)].append(volume)
    claimed_names = claimed_basenames(claimed)
    plan: list[dict] = []
    seen: set[str] = set()
    for folder in folders:
        mapped = container_path(folder)
        key = folder_key(mapped)
        if key in seen or skip_folder(mapped) or key in claimed:
            continue
        name_key = basename_key(mapped)
        if name_key in claimed_names:
            continue
        if len(name_key) < 6:
            continue
        volume = unique.get(key)
        if volume is None:
            volume = unique_names.get((tree_name(mapped), name_key))
        if volume is None:
            volume = best_shared_volume(mapped, by_folder.get(key, []))
        comic_id = str(int(volume["comicvine_id"])) if volume else None
        if comic_id and comic_id in used_ids:
            continue
        comic_name, comic_year = parse_folder_name(mapped)
        plan.append(
            {
                "folder": mapped,
                "comicvine_id": comic_id,
                "comic_name": comic_name,
                "comic_year": comic_year,
            }
        )
        seen.add(key)
        claimed_names.add(name_key)
        if comic_id:
            used_ids.add(comic_id)
    return plan


def apply_remaining(conn: sqlite3.Connection, root: Path, plan: list[dict]) -> dict:
    seeded_folders = 0
    seeded_rows = 0
    skipped_empty = 0
    for item in plan:
        files = archive_files(root, item["folder"])
        if not files:
            skipped_empty += 1
            continue
        seeded_rows += seed_folder_rows(
            conn,
            item["folder"],
            files,
            comic_id=item.get("comicvine_id"),
            comic_name=item["comic_name"],
            comic_year=item.get("comic_year"),
        )
        seeded_folders += 1
    collapsed = collapse_stamped_groups(conn)
    return {
        "seeded_folders": seeded_folders,
        "seeded_rows": seeded_rows,
        "skipped_empty": skipped_empty,
        "collapsed": collapsed,
    }


def import_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT Status, COUNT(*) FROM importresults GROUP BY Status").fetchall()
    return {str(status or "None"): int(count) for status, count in rows}


def comic_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0])


def remaining_stamped(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT ComicID)
              FROM importresults
             WHERE Status = 'Not Imported'
               AND ComicID IS NOT NULL
               AND ComicID != ''
               AND ComicID != 'None'
            """
        ).fetchone()[0]
    )


def remaining_groups(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT 1
                  FROM importresults
                 WHERE Status = 'Not Imported'
                 GROUP BY DynamicName, Volume
            )
            """
        ).fetchone()[0]
    )


def db_status(conn: sqlite3.Connection) -> dict:
    return {
        "comics": comic_count(conn),
        "import_counts": import_counts(conn),
        "remaining_stamped": remaining_stamped(conn),
        "remaining_groups": remaining_groups(conn),
    }


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe = [(key, "<redacted>" if key.lower() in {"apikey", "api_key"} else value) for key, value in query]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe), parsed.fragment)
    )


class Mylar:
    def __init__(self, base: str, timeout: int = 120) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, query: dict | None = None, timeout: int | None = None) -> tuple[int, str]:
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return int(resp.status), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read().decode("utf-8", "replace")

    def scan(self, path: str, timeout: int = 3600) -> tuple[int, str]:
        return self.get("/comicScan", scan_query(path), timeout=timeout)

    def import_status(self) -> str:
        code, body = self.get("/Check_ImportStatus", timeout=15)
        if code >= 400:
            raise RuntimeError(f"import status HTTP {code}")
        return body.strip()

    def massimport(self) -> tuple[int, str]:
        return self.get("/markImports", {"action": "massimport"}, timeout=60)

    def api(self, cmd: str, api_key: str, extra: dict | None = None) -> dict:
        query = {"cmd": cmd, "apikey": api_key}
        query.update(extra or {})
        code, body = self.get("/api", query, timeout=30)
        if code >= 400:
            raise RuntimeError(f"api {cmd} HTTP {code}")
        return json.loads(body)


def wait_scan(client: Mylar, timeout: int = 3600) -> str:
    deadline = time.time() + timeout
    status = ""
    while time.time() < deadline:
        status = client.import_status()
        if status in {"Import completed.", "Failure"}:
            return status
        time.sleep(5)
    raise TimeoutError(f"scan still {status!r}")


def summary(payload: dict) -> dict:
    dumped = json.dumps(payload)
    if "apikey=" in dumped.lower() or "comicvine_api" in dumped:
        raise RuntimeError("summary leaked a secret")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "scan-query",
            "stamp-plan",
            "stamp",
            "collapse",
            "seed-remaining",
            "status",
            "summary-check",
        ),
    )
    parser.add_argument("--path", default=COMIC_ROOT)
    parser.add_argument("--volumes-json")
    parser.add_argument("--db")
    parser.add_argument("--comics-root", default=COMIC_ROOT)
    args = parser.parse_args(argv)
    if args.command == "scan-query":
        json.dump(scan_query(args.path), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command in {"stamp-plan", "stamp"}:
        volumes = json.loads(Path(args.volumes_json).read_text(encoding="utf-8"))
        updates = stamp_updates(volumes)
        if args.command == "stamp-plan":
            json.dump(
                {"updates": [{"comicvine_id": cv, "prefix": prefix} for cv, prefix in updates]},
                sys.stdout,
            )
            sys.stdout.write("\n")
            return 0
        conn = sqlite3.connect(args.db)
        changed = apply_stamps(conn, updates)
        collapsed = collapse_stamped_groups(conn)
        json.dump(
            {"stamped_rows": changed, "folders": len(updates), "collapsed": collapsed},
            sys.stdout,
        )
        sys.stdout.write("\n")
        return 0
    if args.command == "collapse":
        conn = sqlite3.connect(args.db)
        json.dump({"collapsed": collapse_stamped_groups(conn)}, sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "status":
        conn = sqlite3.connect(args.db)
        json.dump(summary(db_status(conn)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "seed-remaining":
        volumes = json.loads(Path(args.volumes_json).read_text(encoding="utf-8"))
        root = Path(args.comics_root)
        conn = sqlite3.connect(args.db)
        plan = remaining_plan(
            series_folders(root),
            volumes,
            claimed_parents(conn),
            used_comic_ids(conn),
        )
        result = apply_remaining(conn, root, plan)
        result["planned_folders"] = len(plan)
        json.dump(summary(result), sys.stdout)
        sys.stdout.write("\n")
        return 0
    json.dump(summary({"ok": True, "path": COMIC_ROOT}), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
