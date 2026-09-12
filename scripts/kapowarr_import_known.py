#!/usr/bin/env python3
"""Import Kapowarr volumes for folders Comicarr already matched.

Uses Library Import with rename_files=false. One folder at a time so
ComicVine 420 cannot stall the whole library.
"""

from __future__ import annotations

import glob as globlib
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KAP_DB = Path("/app/db/Kapowarr.db")
COMIC_DB = Path("/config/comicarr/comicarr.db")
BASE = "http://127.0.0.1:5656/api"


def kap_key() -> str:
    value = sqlite3.connect(str(KAP_DB)).execute(
        "SELECT value FROM config WHERE key='api_key'"
    ).fetchone()[0]
    return value.decode() if isinstance(value, bytes) else str(value)


def request(method: str, path: str, query: dict | None = None, body=None, timeout: int = 600):
    params = dict(query or {})
    params["api_key"] = kap_key()
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:400]}


def folders_from_host_list(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def import_folder(folder: str) -> int:
    status, payload = request(
        "GET",
        "/libraryimport",
        query={
            "folder_filter": globlib.escape(folder),
            "limit": "80",
            "only_english": "false",
            "limit_parent_folder": "false",
        },
        timeout=300,
    )
    if status != 200:
        print(f"propose {folder} HTTP {status} {payload}", flush=True)
        return 0
    rows = payload.get("result") or []
    matches = []
    for row in rows:
        cv = row.get("cv") if isinstance(row, dict) else None
        filepath = row.get("filepath") if isinstance(row, dict) else None
        if not filepath or not isinstance(cv, dict):
            continue
        cv_id = cv.get("comicvine_id") or cv.get("id")
        if cv_id is None:
            continue
        matches.append({"filepath": filepath, "id": int(cv_id)})
    if not matches:
        print(f"no cv {folder}", flush=True)
        return 0
    status, payload = request(
        "POST",
        "/libraryimport",
        query={"rename_files": "false"},
        body=matches,
        timeout=600,
    )
    print(f"import {folder} files={len(matches)} HTTP {status}", flush=True)
    return 1 if status < 400 else 0


def main() -> int:
    folders = folders_from_host_list(Path("/tmp/kapowarr-folders.txt"))
    print(f"folders {len(folders)}", flush=True)
    imported = 0
    for folder in folders:
        imported += import_folder(folder)
        time.sleep(15)
    con = sqlite3.connect(str(KAP_DB))
    volumes = con.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]
    issues = con.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    print(f"done imported_ok={imported} volumes={volumes} issues={issues} files={files}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
