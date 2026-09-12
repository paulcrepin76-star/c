#!/usr/bin/env python3
"""Scan Comicarr Import tiles and import every matched series.

Runs inside the comicarr container. Mints a UI session from the persisted
JWT key, scans comics then manga, confirms matched IDs, and rebinds each
new series to the real folder recorded in ``.source`` so Import does not
create empty ``$Series ($Year)`` folders next to the imprint trees.

Does not move or rename library files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

COOKIE = "comicarr_session"
CSRF = "ComicarrFrontend"
BASE = "http://127.0.0.1:8090"
JWT_KEY = Path("/config/comicarr/.secure/jwt.key")
DB = Path("/config/comicarr/comicarr.db")
COMIC_SCAN = Path("/comics/.comicarr-scan")
MANGA_SCAN = Path("/manga/.comicarr-scan")
SOURCE_MARKER = ".source"


def session_token() -> str:
    key = JWT_KEY.read_bytes()
    token = jwt.encode(
        {
            "sub": "deicide",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=43800),
            "gen": 0,
        },
        key,
        algorithm="HS256",
    )
    return token.decode() if isinstance(token, bytes) else token


def api(method: str, path: str, body=None, timeout: int = 120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Cookie": f"{COOKIE}={session_token()}",
            "X-Requested-With": CSRF,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"detail": raw[:500]}
        return exc.code, payload


def poll_scan(kind: str, timeout: int = 6 * 60 * 60) -> dict:
    path = f"/api/import/{kind}/progress"
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        status, payload = api("GET", path)
        if status != 200:
            raise RuntimeError(f"{kind} progress HTTP {status}: {payload}")
        state = payload.get("status") or "idle"
        progress = payload.get("progress") or {}
        line = (
            f"{kind} {state} processed={progress.get('processed_files')} "
            f"series={progress.get('series_found')} matched={progress.get('series_matched')} "
            f"current={progress.get('current_series')}"
        )
        if line != last:
            print(line, flush=True)
            last = line
        if state in {"completed", "error"} and payload.get("scan_id"):
            return payload
        if state == "error" and not payload.get("scan_id"):
            raise RuntimeError(f"{kind} scan failed: {payload}")
        time.sleep(8)
    raise TimeoutError(f"{kind} scan timed out")


def source_dir(scan_root: Path, series_name: str) -> Path | None:
    marker = scan_root / series_name / SOURCE_MARKER
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        path = Path(text)
        if path.is_dir():
            return path
    folder = scan_root / series_name
    if not folder.exists():
        return None
    for item in folder.iterdir():
        if item.is_symlink() and item.suffix.lower() in {
            ".cbz",
            ".cbr",
            ".cb7",
            ".cbt",
            ".zip",
            ".rar",
            ".7z",
            ".epub",
            ".pdf",
        }:
            try:
                return item.resolve().parent
            except OSError:
                continue
    return None


def matched_ids(results: list) -> list[str]:
    ids = []
    for row in results or []:
        if not row.get("matched") or not row.get("match"):
            continue
        comic_id = row["match"].get("comicid")
        if comic_id:
            ids.append(str(comic_id))
    return ids


def rebind_locations(kind: str, results: list) -> int:
    scan_root = COMIC_SCAN if kind == "comic" else MANGA_SCAN
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    rebound = 0
    for row in results or []:
        if not row.get("matched") or not row.get("match"):
            continue
        comic_id = str(row["match"].get("comicid") or "")
        series_name = row.get("series_name") or ""
        if not comic_id or not series_name:
            continue
        target = source_dir(scan_root, series_name)
        if target is None:
            print(f"rebind skip {kind} {series_name}: no source folder", flush=True)
            continue
        current = cur.execute(
            "SELECT ComicLocation FROM comics WHERE ComicID = ?",
            (comic_id,),
        ).fetchone()
        if current is None:
            print(f"rebind skip {kind} {series_name}: not in db yet", flush=True)
            continue
        old = current[0]
        new = str(target)
        if old == new:
            continue
        cur.execute("UPDATE comics SET ComicLocation = ? WHERE ComicID = ?", (new, comic_id))
        rebound += 1
        leftover = Path(old) if old else None
        if leftover and leftover.is_dir() and leftover.resolve() != target.resolve():
            comic_exts = {".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".epub", ".pdf"}
            leftovers = [
                item
                for item in leftover.rglob("*")
                if item.is_file() and item.suffix.lower() in comic_exts
            ]
            if not leftovers:
                try:
                    shutil.rmtree(leftover)
                except OSError:
                    pass
        print(f"rebind {comic_id} {old} -> {new}", flush=True)
    con.commit()
    con.close()
    return rebound


def refresh_ids(ids: list[str]) -> None:
    for comic_id in ids:
        status, payload = api("POST", f"/api/series/{comic_id}/refresh", {}, timeout=300)
        print(f"refresh {comic_id} HTTP {status}", flush=True)
        if status >= 400:
            print(payload, flush=True)


def start_scan(kind: str) -> dict:
    print(f"=== start {kind} scan ===", flush=True)
    status, payload = api("POST", f"/api/import/{kind}/scan", {})
    print(f"scan start HTTP {status} {payload}", flush=True)
    if status != 200 or not payload.get("success"):
        raise RuntimeError(f"could not start {kind} scan: {payload}")
    return poll_scan(kind)


def import_kind(kind: str) -> dict:
    progress = start_scan(kind)
    results = progress.get("results") or []
    scan_id = progress.get("scan_id")
    matched = matched_ids(results)
    if kind == "comic" and results and not matched:
        print("comic scan matched nothing; waiting for ComicVine and retrying once", flush=True)
        time.sleep(180)
        progress = start_scan(kind)
        results = progress.get("results") or []
        scan_id = progress.get("scan_id")
        matched = matched_ids(results)
    unmatched = [row.get("series_name") for row in results if not row.get("matched")]
    print(
        f"{kind} scan_id={scan_id} rows={len(results)} matched={len(matched)} unmatched={len(unmatched)}",
        flush=True,
    )
    for name in unmatched:
        print(f"{kind} unmatched: {name}", flush=True)
    if matched:
        print(f"=== confirm {len(matched)} {kind} series ===", flush=True)
        status, payload = api(
            "POST",
            f"/api/import/{kind}/confirm",
            {"scan_id": scan_id, "selected_ids": matched},
            timeout=8 * 60 * 60,
        )
        print(f"confirm HTTP {status} {payload}", flush=True)
        rebound = rebind_locations(kind, results)
        print(f"rebound {rebound} {kind} locations", flush=True)
        refresh_ids(matched)
    return {
        "kind": kind,
        "found": len(results),
        "matched": len(matched),
        "unmatched": unmatched,
        "confirm": payload if matched else None,
    }


def db_counts() -> dict:
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    comics = cur.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
    issues = cur.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    with_files = cur.execute(
        "SELECT COUNT(DISTINCT ComicID) FROM issues WHERE Status = 'Downloaded'"
    ).fetchone()[0]
    con.close()
    return {"comics": comics, "issues": issues, "downloaded_series": with_files}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan and import Comicarr libraries")
    parser.add_argument("--only", choices=("all", "comic", "manga"), default="all")
    args = parser.parse_args()
    status, payload = api("GET", "/api/series")
    if status != 200:
        raise SystemExit(f"auth failed HTTP {status}: {payload}")
    print("auth ok", flush=True)
    before = db_counts()
    print(f"before {before}", flush=True)
    comics = None
    manga = None
    if args.only in {"all", "comic"}:
        comics = import_kind("comic")
    if args.only in {"all", "manga"}:
        manga = import_kind("manga")
    after = db_counts()
    print(f"after {after}", flush=True)
    summary = {"before": before, "after": after, "comics": comics, "manga": manga}
    Path("/tmp/comicarr-import-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("before", "after")}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
