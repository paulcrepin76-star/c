#!/usr/bin/env python3
"""Import disk folders that Kapowarr does not have as volumes yet.

Looks up ComicVine IDs (Kapowarr's own search returns none), then uses
Library Import with ``rename_files=false`` so Kavita paths stay put.
Manga paths and foreign-language reprint trees are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

import kapowarr_cleanup as kc

FOLDER_YEAR = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*$")
DC_TREES = {
    "absolute dc",
    "dc comics",
    "dc new 52",
    "dc rebirth",
    "dial r studios",
}
MARVEL_TREES = {
    "amazing spiderman",
    "marvel",
}
FOREIGN_TREES = {
    "ecc ediciones",
    "ediciones zinco",
    "editorial muchnik",
    "editorial novaro",
    "marvel integral",
    "marvel ukpanini uk",
    "panini verlag",
    "pika édition",
    "pika edition",
    "sage - sagédition",
    "sage - sagedition",
    "urban comics",
}
SKIP_FOLDER_MARKERS = (
    "all-new marvel now! previews",
    "marvel intégrale",
    "marvel integrale",
    "mpd-psycho",
    "mpd psycho",
    "dc rebirth omnibus",
    "complete english comic collection",
)
PREFIX_WORDS = (
    "future state",
    "tales from the dark multiverse",
    "the batman who laughs",
    "the green lantern",
    "the infected",
    "justice league",
    "green lantern",
    "harley quinn",
    "suicide squad",
    "teen titans",
    "red hood",
    "batman beyond",
    "wonder woman",
    "mother panic",
    "secret wars",
)


def normalize_title(title: str) -> str:
    text = (title or "").lower().replace("&", " and ").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def folder_meta(path: str) -> tuple[str, int | None, str]:
    """Return ``(title, year, tree)`` from a container folder path.

    Year comes from the folder name only. New 52 / Rebirth trees without a
    year in the name keep ``year=None`` so matching uses the tree window
    (2011-2016 / 2016-2021) instead of pretending every folder is 2011 or
    2016. That 2011 default dropped Batman Eternal, Grayson, Gotham
    Academy, and other 2013-2015 New 52 series.
    """
    parsed = Path(path.rstrip("/"))
    name = parsed.name
    tree = parsed.parent.name
    match = FOLDER_YEAR.match(name)
    if match:
        return match.group("title"), int(match.group("year")), tree
    return name, None, tree


def search_query(title: str) -> str:
    """Broad ComicVine ``name:`` query that can cover a family of folders."""
    key = normalize_title(title)
    for prefix in PREFIX_WORDS:
        if key == prefix or key.startswith(prefix + " "):
            return prefix
    words = key.split()
    if len(words) >= 3 and words[0] == "the":
        return " ".join(words[:3])
    return " ".join(words[:2]) if len(words) >= 2 else key


def should_skip_folder(path: str, *, include_foreign: bool = False) -> str | None:
    if kc.is_manga_path(path):
        return "manga"
    lowered = path.lower()
    tree = Path(path.rstrip("/")).parent.name.lower()
    if any(marker in lowered for marker in SKIP_FOLDER_MARKERS):
        return "skip-list"
    if not include_foreign and tree in FOREIGN_TREES:
        return "foreign"
    return None


def year_fits(folder_year: int | None, cv_year: int | None, tree: str) -> bool:
    if cv_year is None:
        return folder_year is None
    if folder_year is not None:
        return abs(cv_year - folder_year) <= 1
    tree_key = tree.lower()
    if tree_key == "dc new 52":
        return 2011 <= cv_year <= 2016
    if tree_key == "dc rebirth":
        return 2016 <= cv_year <= 2021
    return True


def publisher_name(row: dict) -> str:
    publisher = row.get("publisher")
    if isinstance(publisher, dict):
        return str(publisher.get("name") or "")
    return str(publisher or "")


def publisher_fits(row: dict, tree: str) -> bool:
    tree_key = tree.lower()
    name = publisher_name(row).lower()
    if not name:
        return True
    if tree_key in DC_TREES:
        return "dc" in name
    if tree_key in MARVEL_TREES:
        return "marvel" in name
    return True


def pick_comicvine_volume(
    candidates: list[dict],
    title: str,
    year: int | None,
    tree: str,
) -> dict | None:
    """Pick one ComicVine volume for a disk folder."""
    wanted = normalize_title(title)
    if not wanted:
        return None
    exact: list[dict] = []
    for row in candidates:
        if normalize_title(str(row.get("name") or "")) != wanted:
            continue
        try:
            cv_year = int(row["start_year"]) if row.get("start_year") not in (None, "") else None
        except (TypeError, ValueError):
            cv_year = None
        if not year_fits(year, cv_year, tree):
            continue
        if not publisher_fits(row, tree):
            continue
        item = dict(row)
        item["_year"] = cv_year
        exact.append(item)
    if not exact:
        return None
    if year is not None:
        exact.sort(key=lambda row: (abs((row.get("_year") or year) - year), -(row.get("count_of_issues") or 0)))
        return exact[0]
    tree_key = tree.lower()
    if tree_key == "dc new 52":
        exact.sort(key=lambda row: (row.get("_year") or 9999, -(row.get("count_of_issues") or 0)))
        return exact[0]
    if tree_key == "dc rebirth":
        exact.sort(
            key=lambda row: (
                0 if row.get("_year") == 2016 else 1,
                row.get("_year") or 9999,
                -(row.get("count_of_issues") or 0),
            )
        )
        return exact[0]
    if len({row.get("_year") for row in exact}) > 1:
        return None
    exact.sort(key=lambda row: -(row.get("count_of_issues") or 0))
    return exact[0]


def existing_volume_for_folder(volumes: list[dict], path: str) -> dict | None:
    """Return a Kapowarr volume only when it already uses this disk folder.

    Matching a same-title volume in another tree is unsafe: Kapowarr Library
    Import moves the files into that volume folder on VolumeAlreadyAdded.
    """
    title, year, tree = folder_meta(path)
    key = kc.series_key(title)
    folder = kc.folder_key(path).lower()
    same_folder = [
        item
        for item in volumes
        if kc.folder_key(str(item.get("folder") or "")).lower() == folder
        and item.get("comicvine_id")
        and year_fits(year, item.get("year"), tree)
    ]
    if len(same_folder) == 1:
        return same_folder[0]
    if len(same_folder) > 1:
        same_folder.sort(key=lambda item: -(item.get("issues_downloaded") or 0))
        return same_folder[0]
    matches = [
        item
        for item in volumes
        if kc.series_key(str(item.get("title") or "")) == key
        and item.get("comicvine_id")
        and year_fits(year, item.get("year"), tree)
        and kc.folder_key(str(item.get("folder") or "")).lower() == folder
    ]
    if len(matches) == 1:
        return matches[0]
    return None


HOST_COMICS = "/mnt/user/media/book/comics"


def container_to_host(path: str) -> str:
    text = path.rstrip("/")
    if text == "/comics" or text.startswith("/comics/"):
        return HOST_COMICS + text[len("/comics") :]
    return text


def host_to_container(path: str) -> str:
    text = path.rstrip("/")
    if text == HOST_COMICS or text.startswith(HOST_COMICS + "/"):
        return "/comics" + text[len(HOST_COMICS) :]
    return text


def disk_files_from_find(stdout: str) -> list[str]:
    files = []
    for line in stdout.splitlines():
        host = line.strip()
        if host:
            files.append(host_to_container(host))
    return files


def relative_volume_folder(path: str) -> str:
    text = path.rstrip("/")
    for prefix in ("/comics/", "/comics"):
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip("/")
    return text.lstrip("/")


def import_rows_for_folder(filepaths: list[str], comicvine_id: int) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for filepath in filepaths:
        if not kc.is_archive(filepath) or kc.is_manga_path(filepath):
            continue
        if filepath in seen:
            continue
        seen.add(filepath)
        rows.append({"filepath": filepath, "id": int(comicvine_id)})
    return rows


class ComicVine:
    def __init__(
        self,
        api_key: str,
        cache_path: Path | None = None,
        *,
        cache_only: bool = True,
    ) -> None:
        self.api_key = api_key
        self.cache_path = cache_path
        self.cache_only = cache_only
        self.cache: dict[str, list[dict]] = {}
        if cache_path and cache_path.is_file():
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.cache = {str(key): list(value) for key, value in raw.items()}

    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=2) + "\n", encoding="utf-8")

    def volumes_named(self, name: str) -> list[dict]:
        key = normalize_title(name)
        cached = self.cache.get(key)
        if cached:
            return cached
        if self.cache_only:
            return list(cached or [])
        rows = self._fetch_all(name)
        self.cache[key] = rows
        self.save()
        return rows

    def _fetch_all(self, name: str) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        total = None
        while total is None or offset < total:
            payload = self._request(name, offset=offset)
            total = int(payload.get("number_of_total_results") or 0)
            page = payload.get("results") or []
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            offset += len(page)
            if len(page) < 100:
                break
            time.sleep(8)
        return rows

    def _request(self, name: str, offset: int) -> dict:
        params = {
            "api_key": self.api_key,
            "format": "json",
            "filter": f"name:{name}",
            "field_list": "id,name,start_year,count_of_issues,publisher",
            "limit": "100",
            "offset": str(offset),
        }
        url = "https://comicvine.gamespot.com/api/volumes/?" + urllib.parse.urlencode(params)
        if "/search" in url:
            raise RuntimeError("Refusing ComicVine /search; use /volumes with name:")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "KapowarrUnmatchedImport/1.0"},
        )
        wait = 90
        for attempt in range(8):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    return json.loads(resp.read().decode() or "{}")
            except urllib.error.HTTPError as exc:
                if exc.code != 420:
                    raise
                print(f"ComicVine 420 for {name!r}, waiting {wait}s", flush=True)
                time.sleep(wait)
                wait = min(1800, wait * 2)
                if attempt == 7:
                    raise
        return {}


def list_folder_files(client: kc.Kapowarr, folder: str) -> list[str]:
    """List archives on disk. Never call GET /libraryimport (that hits /search)."""
    del client
    host = container_to_host(folder)
    cmd = (
        "find "
        + shlex.quote(host)
        + " -maxdepth 1 -type f \\( -iname '*.cbz' -o -iname '*.cbr' "
        + "-o -iname '*.cb7' -o -iname '*.cbt' -o -iname '*.pdf' \\)"
    )
    result = subprocess.run(
        ["sudo", "tailscale", "ssh", "root@lerouxfamily", cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"disk list fail {folder}: {result.stderr.strip()[:200]}", flush=True)
        return []
    return disk_files_from_find(result.stdout)


def load_folders(path: str) -> list[str]:
    folders = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            folders.append(text.rstrip("/"))
    return folders


def cmd_import_unmatched(client: kc.Kapowarr, args: argparse.Namespace) -> int:
    volumes = client.volumes()
    volume_folders = {kc.folder_key(str(item.get("folder") or "")).lower() for item in volumes}
    settings = client.settings()
    cv_key = str(settings.get("comicvine_api_key") or "")
    vine = ComicVine(
        cv_key,
        Path(args.cache) if args.cache else None,
        cache_only=not args.fetch_cv,
    )

    folders = load_folders(args.folders_file)
    summary: dict[str, Any] = {
        "folders": len(folders),
        "imported_folders": 0,
        "imported_files": 0,
        "skipped": defaultdict(list),
        "failed": [],
        "matched": [],
    }

    pending: list[str] = []
    existing_first: list[tuple[str, dict]] = []
    for folder in folders:
        reason = should_skip_folder(folder, include_foreign=args.include_foreign)
        if reason:
            summary["skipped"][reason].append(folder)
            continue
        if folder.lower() in volume_folders:
            summary["skipped"]["already-volume"].append(folder)
            continue
        existing = existing_volume_for_folder(volumes, folder)
        if existing and existing.get("comicvine_id"):
            existing_first.append((folder, existing))
        else:
            pending.append(folder)

    print(
        f"import unmatched existing={len(existing_first)} need-cv={len(pending)} "
        f"skipped={ {k: len(v) for k, v in summary['skipped'].items()} }",
        flush=True,
    )

    cv_folders = {
        int(item["comicvine_id"]): str(item.get("folder") or "")
        for item in volumes
        if item.get("comicvine_id")
    }

    def import_folder(folder: str, picked: dict) -> bool:
        if max_folders and summary["imported_folders"] >= max_folders:
            summary["skipped"]["max-folders"].append(folder)
            return False
        cv_id = int(picked["id"])
        existing_folder = cv_folders.get(cv_id)
        if existing_folder and kc.folder_key(existing_folder).lower() != kc.folder_key(folder).lower():
            summary["skipped"]["existing-elsewhere"].append(folder)
            print(
                f"skip existing-elsewhere {folder} already {existing_folder} cv={cv_id}",
                flush=True,
            )
            return True
        files = list_folder_files(client, folder)
        rows = import_rows_for_folder(files, int(picked["id"]))
        if not rows:
            summary["skipped"]["no-files"].append(folder)
            print(f"skip no-files {folder}", flush=True)
            return True
        print(
            f"import {folder} files={len(rows)} cv={picked['id']} "
            f"{picked.get('name')} ({picked.get('start_year')}) via {picked['source']}",
            flush=True,
        )
        if args.dry_run:
            summary["imported_folders"] += 1
            summary["imported_files"] += len(rows)
            summary["matched"].append({"folder": folder, **picked, "files": len(rows)})
            return True
        try:
            client.import_files(rows, rename_files=False)
        except Exception as exc:
            summary["failed"].append({"folder": folder, "error": str(exc)})
            print(f"import fail {folder}: {exc}", flush=True)
            return True
        summary["imported_folders"] += 1
        summary["imported_files"] += len(rows)
        summary["matched"].append({"folder": folder, **picked, "files": len(rows)})
        cv_folders[cv_id] = folder
        time.sleep(0.4)
        return True

    max_folders = int(getattr(args, "max_folders", 0) or 0)

    for folder, existing in existing_first:
        if not import_folder(
            folder,
            {
                "id": int(existing["comicvine_id"]),
                "name": existing.get("title"),
                "start_year": existing.get("year"),
                "source": "existing-volume",
            },
        ):
            break

    if args.existing_only:
        summary["skipped"]["need-cv"] = pending
        pending = []

    by_query: dict[str, list[str]] = defaultdict(list)
    for folder in pending:
        title, _year, _tree = folder_meta(folder)
        by_query[search_query(title)].append(folder)

    for query, group in by_query.items():
        try:
            cached = normalize_title(query) in vine.cache
            candidates = vine.volumes_named(query)
        except Exception as exc:
            print(f"comicvine fail {query!r}: {exc}", flush=True)
            for folder in group:
                summary["failed"].append({"folder": folder, "error": str(exc)})
            time.sleep(8)
            continue
        if not cached and not vine.cache_only:
            time.sleep(8)
        for folder in group:
            title, year, tree = folder_meta(folder)
            match = pick_comicvine_volume(candidates, title, year, tree)
            if not match:
                reason = "no-cv-cache" if vine.cache_only else "no-cv-match"
                summary["skipped"][reason].append(folder)
                print(f"skip {reason} {folder}", flush=True)
                continue
            if not import_folder(
                folder,
                {
                    "id": int(match["id"]),
                    "name": match.get("name"),
                    "start_year": match.get("start_year"),
                    "source": "comicvine-cache" if cached or vine.cache_only else "comicvine",
                },
            ):
                break
        else:
            continue
        break

    volumes = client.volumes()
    summary["after"] = {
        "volumes": len(volumes),
        "downloaded": sum(item.get("issues_downloaded") or 0 for item in volumes),
        "issues": sum(item.get("issue_count") or 0 for item in volumes),
        "stats": client.stats(),
    }
    summary["skipped"] = {key: values for key, values in summary["skipped"].items()}
    text = json.dumps(summary, indent=2)
    print(text, flush=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


def add_unmatched_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "unmatched",
        help="Add missing folders by ComicVine ID and import files in place",
    )
    parser.add_argument("--folders-file", required=True, help="Text file of /comics/... folders")
    parser.add_argument("--cache", default="/tmp/kapowarr-cv-cache.json")
    parser.add_argument("--out", help="Write JSON report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-foreign",
        action="store_true",
        help="Also import ECC/Panini/Novaro/Urban reprint trees",
    )
    parser.add_argument(
        "--existing-only",
        action="store_true",
        help="Only attach files to volumes Kapowarr already has (no ComicVine)",
    )
    parser.add_argument(
        "--fetch-cv",
        action="store_true",
        help="Allow ComicVine /volumes name: lookups for cache misses. Never uses /search.",
    )
    parser.add_argument(
        "--max-folders",
        type=int,
        default=0,
        help="Stop after this many imported folders (0 = no limit)",
    )
