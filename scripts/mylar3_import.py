#!/usr/bin/env python3
"""Import existing /comics folders into Mylar3 without moving files.

Scan in place (imp_paths=1, imp_move=0, imp_rename=0), stamp ComicVine IDs
from Kapowarr when a folder has exactly one volume, then mass-import.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

COMIC_ROOT = "/comics"
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


def folder_key(path: str) -> str:
    return str(path or "").rstrip("/").lower()


def is_imprint_root(path: str) -> bool:
    return folder_key(path) in IMPRINT_ROOTS


def is_manga_path(path: str) -> bool:
    lowered = folder_key(path)
    return any(marker in lowered for marker in MANGA_MARKERS)


def parent_dir(path: str) -> str:
    return str(Path(path).parent).rstrip("/")


def scan_query(path: str) -> dict[str, str]:
    if is_manga_path(path):
        raise ValueError("refusing to scan a manga path")
    if not folder_key(path).startswith(COMIC_ROOT):
        raise ValueError("scan path must stay under /comics")
    return {
        "path": path,
        "scan": "1",
        "libraryscan": "0",
        "autoadd": "0",
        "imp_move": "0",
        "imp_paths": "1",
        "imp_rename": "0",
        "imp_metadata": "0",
        "imp_seriesfolders": "1",
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


def import_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT Status, COUNT(*) FROM importresults GROUP BY Status").fetchall()
    return {str(status or "None"): int(count) for status, count in rows}


def comic_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0])


def summary(payload: dict) -> dict:
    dumped = json.dumps(payload)
    if "apikey=" in dumped.lower() or "comicvine_api" in dumped:
        raise RuntimeError("summary leaked a secret")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan-query", "stamp-plan", "stamp", "summary-check"))
    parser.add_argument("--path", default=COMIC_ROOT)
    parser.add_argument("--volumes-json")
    parser.add_argument("--db")
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
        json.dump({"stamped_rows": changed, "folders": len(updates)}, sys.stdout)
        sys.stdout.write("\n")
        return 0
    json.dump(summary({"ok": True, "path": COMIC_ROOT}), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
