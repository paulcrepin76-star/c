#!/usr/bin/env python3
"""Rematch local manga archives onto Comicarr issue rows."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/opt/comicarr")
from comicarr.manga_parser import parse_manga_filename

ARCHIVE_EXT = {".cbz", ".cbr", ".cb7", ".pdf"}


def list_archives(folder: Path) -> list[Path]:
    files = []
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in ARCHIVE_EXT:
            files.append(path)
    return sorted(files)


def rematch(db_path: Path, comic_id: str, folder: Path) -> dict[str, int]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    series = con.execute("SELECT ComicName, ComicLocation FROM comics WHERE ComicID=?", (comic_id,)).fetchone()
    if not series:
        raise SystemExit(f"no series {comic_id}")
    name = series["ComicName"]
    issues = list(con.execute("SELECT IssueID, ChapterNumber, Status FROM issues WHERE ComicID=?", (comic_id,)))
    by_chapter = {}
    for row in issues:
        raw = row["ChapterNumber"]
        if raw in (None, ""):
            continue
        try:
            by_chapter[float(raw)] = row
        except (TypeError, ValueError):
            continue

    parsed_ok = 0
    marked = 0
    unmatched = 0
    for path in list_archives(folder):
        parsed = parse_manga_filename(path.name, series_name=name)
        if not parsed or parsed.get("chapter_number") is None:
            unmatched += 1
            continue
        parsed_ok += 1
        issue = by_chapter.get(float(parsed["chapter_number"]))
        if not issue:
            unmatched += 1
            continue
        if issue["Status"] != "Downloaded":
            con.execute(
                "UPDATE issues SET Status='Downloaded', Location=? WHERE IssueID=?",
                (path.name, issue["IssueID"]),
            )
            marked += 1
            issue = dict(issue)
            issue["Status"] = "Downloaded"
            by_chapter[float(parsed["chapter_number"])] = issue

    have = con.execute(
        "SELECT COUNT(*) FROM issues WHERE ComicID=? AND Status='Downloaded'",
        (comic_id,),
    ).fetchone()[0]
    con.execute(
        "UPDATE comics SET Have=?, ComicLocation=? WHERE ComicID=?",
        (have, str(folder), comic_id),
    )
    con.commit()
    con.close()
    return {
        "files": parsed_ok + unmatched,
        "parsed": parsed_ok,
        "marked": marked,
        "unmatched": unmatched,
        "have": have,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/config/comicarr/comicarr.db")
    parser.add_argument("--comic-id", required=True)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"missing folder {folder}")
    result = rematch(Path(args.db), args.comic_id, folder)
    print("files", result["files"])
    print("parsed", result["parsed"])
    print("marked", result["marked"])
    print("unmatched", result["unmatched"])
    print("have", result["have"])
    print("location", folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
