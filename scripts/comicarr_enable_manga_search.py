#!/usr/bin/env python3
"""Make Comicarr able to search the main manga series and find releases.

Comicarr Interactive Search only queries issues that are Wanted *and* have a
release/issue date. The five series Paul listed were mostly Skipped with empty
dates, so Search reported nothing. Shangri-La Frontier also searches under its
full Japanese title, which Nyaa/Prowlarr do not index.

This script, run inside the Comicarr container:

- backfills chapter dates (and missing volume numbers) from MangaDex
- marks Skipped issues Wanted so they are eligible
- enables Allow packs
- puts a short ``!!`` English alias first in AlternateSearch
- creates a missing series folder when ComicLocation is empty
- checks MangaDex Add-Series search and optional Interactive Search

Does not move or rename library files. Does not print secrets.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERIES = (
    {
        "short_name": "Bleach",
        "queries": ("Bleach",),
        "comic_id": "md-239d6260-d71f-43b0-afff-074e3619e3de",
        "mangadex_id": "239d6260-d71f-43b0-afff-074e3619e3de",
        "folder": "/manga/Shueisha/Bleach (2002)",
    },
    {
        "short_name": "MPD Psycho",
        "queries": ("MPD Psycho",),
        "comic_id": "md-239a9b85-10d8-4d54-8b76-9a679a1ec6d9",
        "mangadex_id": "239a9b85-10d8-4d54-8b76-9a679a1ec6d9",
        "folder": "/manga/MPD Psycho",
    },
    {
        "short_name": "Naruto",
        "queries": ("Naruto",),
        "comic_id": "md-6b1eb93e-473a-4ab3-9922-1a66d2a29a4a",
        "mangadex_id": "6b1eb93e-473a-4ab3-9922-1a66d2a29a4a",
        "folder": "/manga/Naruto (1999)",
    },
    {
        "short_name": "One Piece",
        "queries": ("One Piece",),
        "comic_id": "md-a1c7c817-4e59-43b7-9365-09675a149a6f",
        "mangadex_id": "a1c7c817-4e59-43b7-9365-09675a149a6f",
        "folder": "/manga/Shueisha/One Piece (2009)",
    },
    {
        "short_name": "Shangri-La Frontier",
        "queries": (
            "Shangri-La Frontier",
            "Shangri-La Frontier ~Kusoge Hunter, Kami-gee ni Idoman to su~",
        ),
        "comic_id": "md-29ab6984-7c1d-4d45-b925-25aa082b492e",
        "mangadex_id": "29ab6984-7c1d-4d45-b925-25aa082b492e",
        "folder": "/manga/Kodansha Comics USA/Shangri-La Frontier (2020)",
    },
)

COOKIE = "comicarr_session"
CSRF = "ComicarrFrontend"
BASE = "http://127.0.0.1:8090"
JWT_KEY = Path("/config/comicarr/.secure/jwt.key")
DB = Path("/config/comicarr/comicarr.db")
MANGADEX = "https://api.mangadex.org"
USER_AGENT = "ComicarrHomelab/1.0 (manga-search)"
CONTENT_RATINGS = ("safe", "suggestive", "erotica", "pornographic")


def parse_chapter_number(raw) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def chapter_date(attrs: dict) -> str | None:
    for key in ("publishAt", "readableAt", "createdAt"):
        value = attrs.get(key)
        if not value:
            continue
        text = str(value).strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
    return None


def fallback_series_date(year) -> str:
    try:
        parsed = int(str(year).strip()[:4])
    except (TypeError, ValueError):
        parsed = 2000
    if parsed < 1950 or parsed > datetime.now().year:
        parsed = 2000
    return f"{parsed}-01-01"


def with_erotica_rating(current: str | None) -> str:
    """MPD Psycho is erotica on MangaDex; safe+suggestive search cannot see it."""

    seen = {part.strip().lower() for part in str(current or "safe,suggestive").split(",") if part.strip()}
    seen.add("erotica")
    order = ("safe", "suggestive", "erotica", "pornographic")
    return ",".join([name for name in order if name in seen] + sorted(seen.difference(order)))


def enable_erotica_rating(config_path: Path) -> bool:
    from configparser import ConfigParser

    cfg = ConfigParser()
    cfg.optionxform = str
    cfg.read(config_path)
    if not cfg.has_section("MangaDex"):
        cfg.add_section("MangaDex")
    current = cfg.get("MangaDex", "mangadex_content_rating", fallback="safe,suggestive")
    updated = with_erotica_rating(current)
    if updated == current:
        return False
    cfg.set("MangaDex", "mangadex_content_rating", updated)
    with config_path.open("w") as fh:
        cfg.write(fh)
    return True


def priority_alternate_search(existing: str | None, short_name: str) -> str:
    """Put ``!!short_name`` first so Prowlarr is queried with the English title."""

    seen: set[str] = set()
    others: list[str] = []
    for part in str(existing or "").split("##"):
        name = part.strip()
        if name.startswith("!!"):
            name = name[2:].strip()
        key = name.casefold()
        if not name or key in seen or key == short_name.casefold():
            continue
        seen.add(key)
        others.append(name)
    return "##".join([f"!!{short_name}"] + others)


def merge_feed_chapter(store: dict[float, dict], attrs: dict) -> None:
    number = parse_chapter_number(attrs.get("chapter"))
    if number is None:
        return
    date = chapter_date(attrs)
    volume = str(attrs.get("volume") or "").strip() or None
    current = store.get(number, {"date": None, "volume": None})
    if date and (current["date"] is None or date < current["date"]):
        current["date"] = date
    if volume and not current["volume"]:
        current["volume"] = volume
    store[number] = current


_SESSION_TOKEN = None


def session_token() -> str:
    import jwt

    global _SESSION_TOKEN
    if _SESSION_TOKEN:
        return _SESSION_TOKEN
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
    _SESSION_TOKEN = token.decode() if isinstance(token, bytes) else token
    return _SESSION_TOKEN


def api(method: str, path: str, body=None, timeout: int = 180):
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


def _http_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_mangadex_chapters(manga_id: str) -> dict[float, dict]:
    store: dict[float, dict] = {}
    offset = 0
    limit = 100
    while True:
        # includeFuturePublishAt=1 makes MangaDex return total=0.
        params = [
            ("limit", str(limit)),
            ("offset", str(offset)),
            ("includeEmptyPages", "0"),
            ("order[chapter]", "asc"),
        ]
        for rating in CONTENT_RATINGS:
            params.append(("contentRating[]", rating))
        url = f"{MANGADEX}/manga/{manga_id}/feed?" + urllib.parse.urlencode(params)
        payload = _http_json(url)
        rows = payload.get("data") or []
        for row in rows:
            merge_feed_chapter(store, (row or {}).get("attributes") or {})
        total = int((payload.get("total") if isinstance(payload.get("total"), int) else len(rows)) or 0)
        offset += len(rows)
        if not rows or offset >= total:
            break
        time.sleep(0.25)
    return store


def ensure_folder(path: str) -> bool:
    folder = Path(path)
    if folder.is_dir():
        return False
    folder.mkdir(parents=True, exist_ok=True)
    return True


def apply_series(con: sqlite3.Connection, series: dict, feed: dict[float, dict]) -> dict:
    row = con.execute(
        "SELECT ComicName, ComicYear, AlternateSearch, ComicLocation, AllowPacks, Have, Total "
        "FROM comics WHERE ComicID=?",
        (series["comic_id"],),
    ).fetchone()
    if not row:
        raise SystemExit(f"missing series {series['comic_id']}")
    fallback = fallback_series_date(row["ComicYear"])
    dated = 0
    volumed = 0
    wanted = 0
    issues = list(
        con.execute(
            "SELECT IssueID, ChapterNumber, VolumeNumber, Status, ReleaseDate, IssueDate "
            "FROM issues WHERE ComicID=?",
            (series["comic_id"],),
        )
    )
    for issue in issues:
        number = parse_chapter_number(issue["ChapterNumber"])
        meta = feed.get(number, {}) if number is not None else {}
        date = meta.get("date") or fallback
        if not str(issue["ReleaseDate"] or "").strip() or not str(issue["IssueDate"] or "").strip():
            con.execute(
                "UPDATE issues SET ReleaseDate=?, IssueDate=? WHERE IssueID=?",
                (date, date, issue["IssueID"]),
            )
            dated += 1
        if meta.get("volume") and not str(issue["VolumeNumber"] or "").strip():
            con.execute(
                "UPDATE issues SET VolumeNumber=? WHERE IssueID=?",
                (meta["volume"], issue["IssueID"]),
            )
            volumed += 1
        if issue["Status"] == "Skipped":
            con.execute(
                "UPDATE issues SET Status='Wanted', AcquisitionIntent='wanted' WHERE IssueID=?",
                (issue["IssueID"],),
            )
            wanted += 1

    alt = priority_alternate_search(row["AlternateSearch"], series["short_name"])
    location = series["folder"]
    created = ensure_folder(location)
    con.execute(
        "UPDATE comics SET AlternateSearch=?, AllowPacks='1', ComicLocation=? WHERE ComicID=?",
        (alt, location, series["comic_id"]),
    )
    return {
        "name": row["ComicName"],
        "short_name": series["short_name"],
        "issues": len(issues),
        "dated": dated,
        "volumed": volumed,
        "wanted": wanted,
        "folder_created": created,
        "have": row["Have"],
        "total": row["Total"],
        "feed": len(feed),
    }


def verify_metadata_search(series: dict) -> dict:
    hits = []
    for query in series["queries"]:
        status, payload = api("POST", "/api/metadata/search/manga", {"name": query, "limit": 20})
        results = payload.get("results") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(results, list):
            hits.append({"query": query, "ok": False, "error": payload.get("detail") or payload.get("error") or status})
            continue
        match = next((item for item in results if item.get("comicid") == series["comic_id"]), None)
        hits.append(
            {
                "query": query,
                "ok": bool(match),
                "returned": len(results),
                "haveit": None if not match else match.get("haveit"),
                "name": None if not match else match.get("name"),
            }
        )
    return {"comic_id": series["comic_id"], "short_name": series["short_name"], "hits": hits}


def candidate_title(candidate: dict) -> str:
    for key in ("nzbtitle", "title", "nzbname", "kind", "provider"):
        value = candidate.get(key)
        if value:
            return str(value)[:120]
    return "release"


def verify_interactive_search(series: dict, timeout: int = 240) -> dict:
    status, started = api(
        "POST",
        "/api/search/interactive",
        {"entity_type": "series", "entity_id": series["comic_id"], "mode": "unfiltered"},
    )
    if status not in (200, 202) or not started.get("session_id"):
        return {
            "short_name": series["short_name"],
            "ok": False,
            "error": started.get("error") or started.get("detail") or status,
        }
    session_id = started["session_id"]
    deadline = time.time() + timeout
    last = started
    while time.time() < deadline:
        time.sleep(3)
        poll_status, last = api("GET", f"/api/search/interactive/{session_id}")
        if poll_status != 200:
            return {"short_name": series["short_name"], "ok": False, "error": last.get("detail") or poll_status}
        state = last.get("state")
        if state in {"completed", "failed"}:
            break
    titles = [candidate_title(item) for item in (last.get("candidates") or [])[:8]]
    return {
        "short_name": series["short_name"],
        "ok": bool(last.get("candidates")) and last.get("state") == "completed",
        "state": last.get("state"),
        "candidates": last.get("candidate_count") or len(last.get("candidates") or []),
        "titles": titles,
        "failures": [
            {"provider": item.get("provider"), "code": item.get("code")}
            for item in (last.get("provider_failures") or [])[:6]
        ],
    }


def print_report(applied: list[dict], searches: list[dict], interactive: list[dict] | None) -> None:
    print("applied")
    for row in applied:
        print(
            f"  {row['short_name']}: dated={row['dated']} wanted={row['wanted']} "
            f"volumes={row['volumed']} feed={row['feed']} have={row['have']}/{row['total']} "
            f"folder_created={row['folder_created']}"
        )
    if searches:
        print("mangadex_search")
    for row in searches:
        for hit in row["hits"]:
            if hit.get("ok"):
                print(f"  {row['short_name']} query={hit['query']!r} returned={hit['returned']} haveit={hit['haveit']}")
            else:
                print(f"  {row['short_name']} query={hit['query']!r} FAIL {hit.get('error')}")
    if interactive is None:
        return
    print("interactive_search")
    for row in interactive:
        if row.get("ok"):
            print(f"  {row['short_name']}: {row['candidates']} releases")
            for title in row.get("titles") or []:
                print(f"    - {title}")
        else:
            print(f"  {row['short_name']}: FAIL {row.get('error') or row.get('state')} candidates={row.get('candidates', 0)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--config", default="/config/comicarr/config.ini")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--apply-only", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--interactive-timeout", type=int, default=240)
    args = parser.parse_args()

    if not args.verify_only:
        if enable_erotica_rating(Path(args.config)):
            print("config mangadex_content_rating now includes erotica")
        con = sqlite3.connect(args.db)
        con.row_factory = sqlite3.Row
        applied = []
        try:
            for series in SERIES:
                print(f"mangadex_feed {series['short_name']}", flush=True)
                feed = fetch_mangadex_chapters(series["mangadex_id"])
                applied.append(apply_series(con, series, feed))
            con.commit()
        finally:
            con.close()
    else:
        applied = []
        con = sqlite3.connect(args.db)
        con.row_factory = sqlite3.Row
        try:
            for series in SERIES:
                row = con.execute(
                    "SELECT ComicName, Have, Total FROM comics WHERE ComicID=?",
                    (series["comic_id"],),
                ).fetchone()
                wanted = con.execute(
                    "SELECT COUNT(*) FROM issues WHERE ComicID=? AND Status='Wanted'",
                    (series["comic_id"],),
                ).fetchone()[0]
                applied.append(
                    {
                        "short_name": series["short_name"],
                        "dated": 0,
                        "wanted": wanted,
                        "volumed": 0,
                        "feed": 0,
                        "have": None if not row else row["Have"],
                        "total": None if not row else row["Total"],
                        "folder_created": False,
                    }
                )
        finally:
            con.close()

    if args.apply_only:
        print_report(applied, [], None)
        return 0
    searches = [verify_metadata_search(series) for series in SERIES]
    interactive = None
    if args.interactive:
        interactive = [verify_interactive_search(series, timeout=args.interactive_timeout) for series in SERIES]
    print_report(applied, searches, interactive)
    search_ok = all(any(hit.get("ok") for hit in row["hits"]) for row in searches)
    interactive_ok = interactive is None or all(row.get("ok") for row in interactive)
    return 0 if search_ok and interactive_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
