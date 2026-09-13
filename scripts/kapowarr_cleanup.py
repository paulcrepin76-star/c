#!/usr/bin/env python3
"""Clean a Kapowarr library over its HTTP API.

Used from the Cloud Agent (via the Tailscale proxy) or from Unraid.
Does not delete volume folders on disk. Manga paths are ignored.

Steps the ``run`` command can take:

1. Delete comic archives that are empty or tiny (no usable weight).
2. Remove empty duplicate volume *records* that share a title/year/folder
   with a populated volume (``delete_folder=false``).
3. Import unmatched files into an existing volume when the folder or
   rebirth cutover is unambiguous. Rename only when the file sits in the
   wrong series folder (the Action Comics 1938 vs 2016 case).
4. Queue Search All so Kapowarr downloads remaining missing issues.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ARCHIVE_SUFFIXES = (".cbr", ".cbz", ".cb7", ".cbt", ".pdf")
EMPTY_MAX_BYTES = 1024
MANGA_MARKERS = ("/manga/", "/series/")
IMPRINT_ROOTS = {
    "/comics/dc rebirth",
    "/comics/dc new 52",
    "/comics/absolute dc",
    "/comics/marvel",
    "/comics/spider-man",
    "/comics",
}

# Issue numbers at or above this, sitting in an older folder, belong to the
# modern volume of the same title (DC Rebirth numbering).
WRONG_FOLDER_CUTOVER = {
    "action comics": 957,
    "detective comics": 934,
}

KNOWN_MODERN_CV = {
    ("action comics", 2016): 91078,
}


def series_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def parse_issue_number(filename: str) -> float | None:
    stem = Path(filename).stem
    match = re.search(r"(?i)(?:issue|no\.?|#)\s*(\d+(?:\.\d+)?)", stem)
    if match:
        return float(match.group(1))
    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", stem).strip()
    match = re.search(r"(?<!\d)(\d{1,4})(?:\.\d+)?$", stripped)
    if match:
        return float(match.group(1))
    return None


def infer_series_title(filename: str) -> str | None:
    stem = Path(filename).stem
    stem = re.sub(r"\s*\(\d{4}\)\s*", " ", stem)
    stem = re.sub(r"(?i)\s*(volume|vol\.?)\s*\d+\s*", " ", stem)
    stem = re.sub(r"(?i)\s*(issue|no\.?|#)\s*\d+(?:\.\d+)?\s*", " ", stem)
    stem = re.sub(r"\s+\d{3,4}\s*$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return stem or None


def is_manga_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in MANGA_MARKERS)


def is_archive(path: str) -> bool:
    return path.lower().endswith(ARCHIVE_SUFFIXES)


def is_empty_archive(file: dict) -> bool:
    path = str(file.get("filepath") or "")
    if is_manga_path(path) or not is_archive(path):
        return False
    size = file.get("size")
    if size is None:
        return False
    try:
        return int(size) <= EMPTY_MAX_BYTES
    except (TypeError, ValueError):
        return False


def folder_key(path: str) -> str:
    return (path or "").rstrip("/")


def is_imprint_root(folder: str) -> bool:
    return folder_key(folder).lower() in IMPRINT_ROOTS


def empty_duplicate_volume_ids(volumes: list[dict], *, ignore_year: bool = False) -> list[int]:
    """Empty volume records that share a title and folder with a populated one."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for volume in volumes:
        key = (
            series_key(str(volume.get("title") or "")),
            None if ignore_year else volume.get("year"),
            folder_key(str(volume.get("folder") or "")),
        )
        groups[key].append(volume)

    delete: list[int] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        populated = [item for item in group if (item.get("issues_downloaded") or 0) > 0]
        empty = [item for item in group if not (item.get("issues_downloaded") or 0)]
        if populated and empty:
            for item in empty:
                # A later run in the same folder (Batman Beyond 2016 next
                # to 2012) is not a duplicate just because it is still empty.
                if ignore_year and (item.get("issue_count") or 0) > 1:
                    continue
                delete.append(int(item["id"]))
    return sorted(set(delete))


def shared_folder_volume(owners: list[dict], issue: float | None) -> dict | None:
    """Pick a volume when more than one series shares a folder."""
    if issue is None or len(owners) < 2:
        return None
    complete = [
        item
        for item in owners
        if (item.get("issue_count") or 0) > 0
        and (item.get("issues_downloaded") or 0) >= (item.get("issue_count") or 0)
    ]
    incomplete = [
        item
        for item in owners
        if (item.get("issues_downloaded") or 0) < (item.get("issue_count") or 1)
    ]
    if len(complete) == 1 and len(incomplete) == 1:
        complete_count = float(complete[0].get("issue_count") or 0)
        if issue > complete_count:
            return incomplete[0]
    if all(not (item.get("issues_downloaded") or 0) for item in owners):
        fitting = [item for item in owners if (item.get("issue_count") or 0) >= issue]
        if not fitting:
            return None
        fitting.sort(key=lambda item: item.get("issue_count") or 0)
        unique_count = {item.get("issue_count") for item in fitting}
        if len(fitting) == 1 or len(unique_count) == len(fitting):
            return fitting[0]
    return None


def volumes_in_folder(volumes: list[dict], folder: str) -> list[dict]:
    target = folder_key(folder)
    return [item for item in volumes if folder_key(str(item.get("folder") or "")) == target]


def modern_volume_for_title(volumes: list[dict], title: str) -> dict | None:
    key = series_key(title)
    candidates = [
        item
        for item in volumes
        if series_key(str(item.get("title") or "")) == key
        and (item.get("year") or 0) >= 2016
        and not is_imprint_root(str(item.get("folder") or ""))
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.get("issues_downloaded") or 0, item.get("year") or 0), reverse=True)
    return candidates[0]


def target_for_unmatched_file(
    filepath: str,
    volumes: list[dict],
) -> tuple[int | None, bool]:
    """Return ``(comicvine_id, rename_files)`` for an unmatched file.

    Rename is True only when the file is in the wrong series folder and must
    move (rebirth issues parked in a golden-age folder).
    """
    if is_manga_path(filepath):
        return None, False

    parent = folder_key(str(Path(filepath).parent))
    filename = Path(filepath).name
    issue = parse_issue_number(filename)
    series = infer_series_title(filename)

    if series and issue is not None:
        cutover = WRONG_FOLDER_CUTOVER.get(series_key(series))
        parent_name = series_key(Path(parent).name)
        if cutover is not None and issue >= cutover:
            in_old_folder = parent_name == series_key(series) or "193" in Path(parent).name
            if in_old_folder or parent_name != series_key(series) + " 2016":
                modern = modern_volume_for_title(volumes, series)
                if modern and folder_key(str(modern.get("folder") or "")) != parent:
                    return int(modern["comicvine_id"]), True
                known = KNOWN_MODERN_CV.get((series_key(series), 2016))
                if known:
                    return known, True

    owners = volumes_in_folder(volumes, parent)
    owners = [item for item in owners if not is_imprint_root(str(item.get("folder") or ""))]
    if len(owners) == 1:
        return int(owners[0]["comicvine_id"]), False
    shared = shared_folder_volume(owners, issue)
    if shared:
        return int(shared["comicvine_id"]), False
    return None, False


def group_import_rows(
    rows: list[dict],
    volumes: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    """Split unmatched files into rename / keep-path import batches."""
    keep: list[dict] = []
    move: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for row in rows:
        filepath = row.get("filepath") if isinstance(row, dict) else None
        if not filepath or filepath in seen or is_manga_path(str(filepath)):
            continue
        seen.add(str(filepath))
        comicvine_id = None
        rename = False
        cv = row.get("cv") if isinstance(row, dict) else None
        if isinstance(cv, dict):
            comicvine_id = cv.get("id") or cv.get("comicvine_id")
        if comicvine_id is None:
            comicvine_id, rename = target_for_unmatched_file(str(filepath), volumes)
        else:
            comicvine_id = int(comicvine_id)
            guessed_id, guessed_rename = target_for_unmatched_file(str(filepath), volumes)
            rename = guessed_rename and guessed_id == comicvine_id
        if comicvine_id is None:
            skipped.append(str(filepath))
            continue
        item = {"filepath": str(filepath), "id": int(comicvine_id)}
        (move if rename else keep).append(item)
    return keep, move, skipped


class Kapowarr:
    def __init__(self, base: str, api_key: str) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        query: dict | None = None,
        body: Any = None,
        timeout: int = 600,
    ) -> tuple[int, dict]:
        params = dict(query or {})
        params["api_key"] = self.api_key
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode() or "{}"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                payload = {"error": raw[:500]}
            return exc.code, payload

    def get(self, path: str, timeout: int = 600, **query: Any) -> Any:
        status, payload = self.request("GET", path, query=query, timeout=timeout)
        if status >= 400:
            raise RuntimeError(f"GET {path} HTTP {status}: {payload}")
        return payload.get("result")

    def volumes(self) -> list[dict]:
        result = self.get("/volumes")
        return result if isinstance(result, list) else []

    def volume(self, volume_id: int) -> dict:
        result = self.get(f"/volumes/{volume_id}")
        return result if isinstance(result, dict) else {}

    def stats(self) -> dict:
        result = self.get("/volumes/stats")
        return result if isinstance(result, dict) else {}

    def settings(self) -> dict:
        result = self.get("/settings")
        return result if isinstance(result, dict) else {}

    def add_volume(self, comicvine_id: int, volume_folder: str, *, auto_search: bool = False) -> tuple[int, dict]:
        body = {
            "comicvine_id": int(comicvine_id),
            "root_folder_id": 1,
            "monitor": True,
            "monitoring_scheme": "all",
            "monitor_new_issues": True,
            "volume_folder": volume_folder,
            "auto_search": auto_search,
        }
        return self.request("POST", "/volumes", body=body, timeout=180)

    def delete_file(self, file_id: int) -> int:
        status, payload = self.request("DELETE", f"/files/{file_id}")
        if status >= 400:
            raise RuntimeError(f"DELETE /files/{file_id} HTTP {status}: {payload}")
        return status

    def delete_volume(self, volume_id: int) -> int:
        status, payload = self.request(
            "DELETE",
            f"/volumes/{volume_id}",
            query={"delete_folder": "false"},
        )
        if status >= 400:
            raise RuntimeError(f"DELETE /volumes/{volume_id} HTTP {status}: {payload}")
        return status

    def library_import(self, *, limit: int = 80, folder_filter: str | None = None) -> list[dict]:
        query: dict[str, Any] = {
            "limit": str(limit),
            "only_english": "false",
            "limit_parent_folder": "false",
        }
        if folder_filter:
            query["folder_filter"] = folder_filter
        result = self.get("/libraryimport", timeout=900, **query)
        return result if isinstance(result, list) else []

    def import_files(self, rows: list[dict], rename_files: bool) -> int:
        if not rows:
            return 0
        wait = 90
        for attempt in range(6):
            status, payload = self.request(
                "POST",
                "/libraryimport",
                query={"rename_files": "true" if rename_files else "false"},
                body=rows,
                timeout=1800,
            )
            rate_limited = status == 509 or (
                isinstance(payload, dict) and payload.get("error") == "CVRateLimitReached"
            )
            if rate_limited:
                print(f"Kapowarr ComicVine 509, waiting {wait}s", flush=True)
                time.sleep(wait)
                wait = min(1800, wait * 2)
                continue
            if status >= 400 or (isinstance(payload, dict) and payload.get("error")):
                raise RuntimeError(f"POST /libraryimport HTTP {status}: {payload}")
            return len(rows)
        raise RuntimeError(f"POST /libraryimport still rate-limited after retries: {payload}")

    def search_all(self) -> dict:
        status, payload = self.request("POST", "/system/tasks", body={"cmd": "search_all"})
        if status >= 400:
            raise RuntimeError(f"POST /system/tasks HTTP {status}: {payload}")
        return payload.get("result") or payload

    def tasks(self) -> list[dict]:
        result = self.get("/system/tasks")
        return result if isinstance(result, list) else []


def collect_files(client: Kapowarr, volumes: list[dict]) -> list[dict]:
    files: list[dict] = []
    for volume in volumes:
        detail = client.volume(int(volume["id"]))
        for issue in detail.get("issues") or []:
            for item in issue.get("files") or []:
                row = dict(item)
                row["volume_id"] = volume["id"]
                row["issue_id"] = issue.get("id")
                row["issue_number"] = issue.get("issue_number")
                files.append(row)
        for item in detail.get("general_files") or []:
            row = dict(item)
            row["volume_id"] = volume["id"]
            files.append(row)
    return files


def load_key(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    env = os.environ.get("KAPOWARR_API_KEY")
    if env:
        return env.strip()
    default = Path("/tmp/kapowarr-api-key")
    if default.is_file():
        return default.read_text(encoding="utf-8").strip()
    raise RuntimeError("Set KAPOWARR_API_KEY or pass --api-key-file")


def cmd_inventory(client: Kapowarr, args: argparse.Namespace) -> int:
    volumes = client.volumes()
    stats = client.stats()
    files = collect_files(client, volumes)
    empty_files = [item for item in files if is_empty_archive(item)]
    empty_dups = empty_duplicate_volume_ids(volumes)
    import_rows = client.library_import(limit=args.limit)
    keep, move, skipped = group_import_rows(import_rows, volumes)
    report = {
        "stats": stats,
        "volume_count": len(volumes),
        "file_count": len(files),
        "empty_archives": [
            {"id": item.get("id"), "size": item.get("size"), "filepath": item.get("filepath")}
            for item in empty_files
        ],
        "empty_duplicate_volume_ids": empty_dups,
        "import_rows": len(import_rows),
        "import_keep": len(keep),
        "import_move": len(move),
        "import_skipped": len(skipped),
        "import_skipped_sample": skipped[:40],
        "zero_download_volumes": [
            {
                "id": item["id"],
                "title": item.get("title"),
                "year": item.get("year"),
                "folder": item.get("folder"),
                "issues": item.get("issue_count"),
            }
            for item in volumes
            if not (item.get("issues_downloaded") or 0)
        ],
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


def _chunks(rows: list[dict], size: int) -> list[list[dict]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def cmd_run(client: Kapowarr, args: argparse.Namespace) -> int:
    summary: dict[str, Any] = {"deleted_files": [], "deleted_volumes": [], "imported_keep": 0, "imported_move": 0}
    volumes = client.volumes()
    summary["before"] = {
        "volumes": len(volumes),
        "downloaded": sum(item.get("issues_downloaded") or 0 for item in volumes),
        "issues": sum(item.get("issue_count") or 0 for item in volumes),
        "stats": client.stats(),
    }

    files = collect_files(client, volumes)
    for item in files:
        if not is_empty_archive(item):
            continue
        file_id = item.get("id")
        if file_id is None:
            continue
        print(f"delete empty file {file_id} {item.get('filepath')} size={item.get('size')}", flush=True)
        if not args.dry_run:
            client.delete_file(int(file_id))
        summary["deleted_files"].append({"id": file_id, "filepath": item.get("filepath"), "size": item.get("size")})

    volumes = client.volumes()
    import_rows = client.library_import(limit=args.limit)
    keep, move, skipped = group_import_rows(import_rows, volumes)
    print(
        f"import candidates keep={len(keep)} move={len(move)} skipped={len(skipped)}",
        flush=True,
    )
    for batch in _chunks(keep, args.batch):
        print(f"import keep batch {len(batch)}", flush=True)
        if not args.dry_run:
            client.import_files(batch, rename_files=False)
        summary["imported_keep"] += len(batch)
        time.sleep(1)
    for batch in _chunks(move, args.batch):
        print(f"import move batch {len(batch)}", flush=True)
        if not args.dry_run:
            client.import_files(batch, rename_files=True)
        summary["imported_move"] += len(batch)
        time.sleep(1)
    summary["import_skipped"] = len(skipped)
    summary["import_skipped_sample"] = skipped[:40]

    volumes = client.volumes()
    for volume_id in empty_duplicate_volume_ids(volumes, ignore_year=True):
        print(f"delete empty duplicate volume {volume_id} (keep folder)", flush=True)
        if not args.dry_run:
            client.delete_volume(volume_id)
        summary["deleted_volumes"].append(volume_id)

    if args.search_all:
        print("queue Search All", flush=True)
        if not args.dry_run:
            summary["search_all"] = client.search_all()
            summary["tasks"] = client.tasks()

    volumes = client.volumes()
    summary["after"] = {
        "volumes": len(volumes),
        "downloaded": sum(item.get("issues_downloaded") or 0 for item in volumes),
        "issues": sum(item.get("issue_count") or 0 for item in volumes),
        "stats": client.stats(),
    }
    text = json.dumps(summary, indent=2)
    print(text, flush=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("KAPOWARR_URL", "http://127.0.0.1:5656/api"))
    parser.add_argument("--api-key-file", default=os.environ.get("KAPOWARR_API_KEY_FILE"))
    sub = parser.add_subparsers(dest="command", required=True)

    def add_shared(target: argparse.ArgumentParser) -> None:
        target.add_argument("--limit", type=int, default=80, help="Library Import folder limit")
        target.add_argument("--batch", type=int, default=20)
        target.add_argument("--out", help="Write JSON report to this path")

    inventory = sub.add_parser("inventory", help="Read-only snapshot")
    add_shared(inventory)
    run = sub.add_parser("run", help="Delete empties, import matches, optional Search All")
    add_shared(run)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--search-all", action="store_true")
    import kapowarr_unmatched as ku

    ku.add_unmatched_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = Kapowarr(args.url, load_key(args.api_key_file))
    if args.command == "inventory":
        return cmd_inventory(client, args)
    if args.command == "run":
        return cmd_run(client, args)
    if args.command == "unmatched":
        import kapowarr_unmatched as ku

        return ku.cmd_import_unmatched(client, args)
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    sys.exit(main())
