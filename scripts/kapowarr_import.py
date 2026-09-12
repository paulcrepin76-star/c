#!/usr/bin/env python3
"""Import every ComicVine-matched folder into Kapowarr.

Runs inside the kapowarr container. Uses Library Import with
``rename_files=false`` so files stay where Kavita already reads them.
Walks one series folder at a time so unmatched imprint rows cannot
block the rest of the library. Manga is imported the same way if
``/manga`` is a root folder.
"""

from __future__ import annotations

import glob as globlib
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comicarr_index as idx

DB = Path("/app/db/Kapowarr.db")
BASE = "http://127.0.0.1:5656/api"
SUMMARY = Path("/tmp/kapowarr-import-summary.json")


def api_key() -> str:
    con = sqlite3.connect(str(DB))
    value = con.execute("SELECT value FROM config WHERE key='api_key'").fetchone()[0]
    con.close()
    if isinstance(value, bytes):
        value = value.decode()
    if not value:
        raise RuntimeError("Kapowarr api_key is empty")
    return str(value)


def request(method: str, path: str, query: dict | None = None, body=None, timeout: int = 600):
    key = api_key()
    params = dict(query or {})
    params["api_key"] = key
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode() or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw[:500]}
        return exc.code, payload


def root_folders() -> list[str]:
    status, payload = request("GET", "/rootfolder")
    if status != 200:
        raise RuntimeError(f"rootfolder HTTP {status}: {payload}")
    result = payload.get("result") or payload
    folders = []
    if isinstance(result, list):
        for item in result:
            folder = item.get("folder") if isinstance(item, dict) else item
            if folder:
                folders.append(str(folder).rstrip("/") + "/")
    return folders


def add_root(folder: str) -> None:
    current = [item.rstrip("/") for item in root_folders()]
    if folder.rstrip("/") in current:
        print(f"root already present {folder}", flush=True)
        return
    status, payload = request("POST", "/rootfolder", body={"folder": folder})
    print(f"add root {folder} HTTP {status}", flush=True)
    if status >= 400:
        print(payload, flush=True)


def propose(folder: str, limit: int = 80, only_english: bool = False, parent: bool = False) -> list:
    status, payload = request(
        "GET",
        "/libraryimport",
        query={
            "folder_filter": globlib.escape(folder),
            "limit": str(limit),
            "only_english": "true" if only_english else "false",
            "limit_parent_folder": "true" if parent else "false",
        },
        timeout=900,
    )
    if status != 200:
        print(f"propose {folder} HTTP {status} {payload}", flush=True)
        return []
    result = payload.get("result")
    if result is None:
        result = payload if isinstance(payload, list) else []
    return result if isinstance(result, list) else []


def import_matches(rows: list) -> int:
    matches = []
    seen = set()
    for row in rows:
        cv = row.get("cv") if isinstance(row, dict) else None
        filepath = row.get("filepath") if isinstance(row, dict) else None
        if not filepath or not isinstance(cv, dict):
            continue
        cv_id = cv.get("id") or cv.get("comicvine_id")
        if cv_id is None:
            continue
        key = (filepath, int(cv_id))
        if key in seen:
            continue
        seen.add(key)
        matches.append({"filepath": filepath, "id": int(cv_id)})
    if not matches:
        return 0
    status, payload = request(
        "POST",
        "/libraryimport",
        query={"rename_files": "false"},
        body=matches,
        timeout=1800,
    )
    print(f"import {len(matches)} files HTTP {status}", flush=True)
    if status >= 400:
        print(payload, flush=True)
        return 0
    return len({item["id"] for item in matches})


def series_folders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    scan = root / idx.SCAN_DIR_NAME
    return [
        path
        for path in idx.collect(root)
        if path.resolve() != scan.resolve() and scan.resolve() not in path.resolve().parents
    ]


def import_tree(root: Path) -> dict:
    folders = series_folders(root)
    print(f"=== kapowarr {root} {len(folders)} series folders ===", flush=True)
    imported = 0
    unmatched = []
    errors = 0
    for folder in folders:
        try:
            rows = propose(str(folder), limit=200, only_english=False)
        except Exception as exc:
            print(f"propose error {folder}: {exc}", flush=True)
            errors += 1
            time.sleep(2)
            continue
        if not rows:
            continue
        added = import_matches(rows)
        imported += added
        if added == 0:
            unmatched.append(str(folder))
        else:
            print(f"imported {added} from {folder}", flush=True)
        time.sleep(0.4)
    return {
        "root": str(root),
        "series_folders": len(folders),
        "imported_volumes": imported,
        "unmatched": unmatched,
        "errors": errors,
    }


def db_counts() -> dict:
    con = sqlite3.connect(str(DB))
    volumes = con.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]
    issues = con.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    con.close()
    return {"volumes": volumes, "issues": issues, "files": files}


def main() -> int:
    before = db_counts()
    print(f"before {before}", flush=True)
    add_root("/comics")
    manga = Path("/manga")
    if manga.is_dir():
        add_root("/manga")
    comics = import_tree(Path("/comics"))
    manga_result = import_tree(manga) if manga.is_dir() else {"root": "/manga", "skipped": True}
    after = db_counts()
    summary = {"before": before, "after": after, "comics": comics, "manga": manga_result}
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"after {after}", flush=True)
    print(
        json.dumps(
            {
                "before": before,
                "after": after,
                "comics_folders": comics.get("series_folders"),
                "comics_imported": comics.get("imported_volumes"),
                "comics_unmatched": len(comics.get("unmatched") or []),
                "manga_folders": manga_result.get("series_folders"),
                "manga_imported": manga_result.get("imported_volumes"),
                "manga_unmatched": len(manga_result.get("unmatched") or []),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
