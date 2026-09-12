#!/usr/bin/env python3
"""Import Comicarr series from a saved 'Matched ... (comicid)' log and rebind folders."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jwt

COOKIE = "comicarr_session"
BASE = "http://127.0.0.1:8090"
DB = Path("/config/comicarr/comicarr.db")
SCAN = Path("/comics/.comicarr-scan")
MATCH_RE = re.compile(r"Matched '(?P<name>.*)' to ComicVine:.*\((?P<cid>\d+)\)\s*$")


def token() -> str:
    key = Path("/config/comicarr/.secure/jwt.key").read_bytes()
    value = jwt.encode(
        {
            "sub": "deicide",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=43800),
            "gen": 0,
        },
        key,
        algorithm="HS256",
    )
    return value.decode() if isinstance(value, bytes) else value


def api(method: str, path: str, body=None, timeout: int = 180):
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Cookie": f"{COOKIE}={token()}",
            "X-Requested-With": "ComicarrFrontend",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"detail": raw[:400]}
        return exc.code, payload


def parse_matches(text: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = MATCH_RE.search(line)
        if not match:
            continue
        comic_id = match.group("cid")
        name = match.group("name")
        found.setdefault(comic_id, name)
    return list(found.items())


def source_dir(series_name: str) -> Path | None:
    marker = SCAN / series_name / ".source"
    if marker.is_file():
        path = Path(marker.read_text(encoding="utf-8").strip())
        if path.is_dir():
            return path
    return None


def rebind(comic_id: str, location: Path) -> None:
    con = sqlite3.connect(str(DB))
    con.execute("UPDATE comics SET ComicLocation = ? WHERE ComicID = ?", (str(location), comic_id))
    con.commit()
    con.close()


def main() -> int:
    match_file = Path("/tmp/comicarr-cv-matches.txt")
    pairs = parse_matches(match_file.read_text(encoding="utf-8", errors="replace"))
    print(f"unique matches {len(pairs)}", flush=True)
    added = 0
    rebound = 0
    for comic_id, name in pairs:
        print(f"add {comic_id} {name}", flush=True)
        status, payload = api("POST", "/api/series", {"id": comic_id}, timeout=300)
        print(f"  http {status} {payload}", flush=True)
        if status == 200:
            added += 1
        target = source_dir(name)
        if target is not None:
            # addComictoDB is queued; wait briefly for the row
            for _ in range(30):
                con = sqlite3.connect(str(DB))
                row = con.execute("SELECT ComicID FROM comics WHERE ComicID = ?", (comic_id,)).fetchone()
                con.close()
                if row:
                    rebind(comic_id, target)
                    rebound += 1
                    print(f"  rebind {target}", flush=True)
                    api("POST", f"/api/series/{comic_id}/refresh", {}, timeout=180)
                    break
                time.sleep(2)
        time.sleep(12)
    print("waiting for queued adds to finish, then rebinding again", flush=True)
    time.sleep(20)
    final = 0
    for comic_id, name in pairs:
        target = source_dir(name)
        if target is None:
            continue
        rebind(comic_id, target)
        final += 1
    con = sqlite3.connect(str(DB))
    comics = con.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
    issues = con.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    con.close()
    print(f"done added={added} rebound={rebound} final_rebind={final} comics={comics} issues={issues}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
