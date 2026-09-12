#!/usr/bin/env python3
"""Explain why Kapowarr (or Omnibus) cannot see the whole comic collection.

Run on Unraid:

  python3 scripts/comics_visibility.py

Or replay a saved snapshot:

  python3 scripts/comics_visibility.py --fixture scripts/tests/fixtures/leroux-comics.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

COMIC_EXTS = {".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".epub", ".pdf"}
WATCH_NAMES = (
    "kapowarr",
    "komga",
    "omnibus",
    "suwayomi",
    "tranga",
    "lazylibrarian",
    "kumiho",
    "kavita",
    "mylar",
)
DEFAULT_TREES = (
    "/mnt/user/media/book",
    "/mnt/user/media/book/manga",
    "/mnt/user/media/book/comics",
    "/mnt/user/media/book/comics/Omnibus Downloads",
    "/mnt/user/omnibus-data",
    "/mnt/user/omnibus-data/comics",
    "/mnt/user/omnibus-data/manga",
    "/mnt/user/omnibus-data/unmatched",
    "/mnt/user/media/animation serie/Bleach/Bleach/Manga",
)
HOST_BOOK = "/mnt/user/media/book"
HOST_MANGA = "/mnt/user/media/book/manga"
HOST_COMICS = "/mnt/user/media/book/comics"
HOST_OMNIBUS_DATA = "/mnt/user/omnibus-data"
HOST_BLEACH = "/mnt/user/media/animation serie/Bleach/Bleach/Manga"


@dataclass
class Mount:
    container: str
    destination: str
    source: str


@dataclass
class TreeCount:
    path: str
    files: int
    exists: bool


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str


@dataclass
class Snapshot:
    containers: list[str] = field(default_factory=list)
    mounts: list[Mount] = field(default_factory=list)
    trees: list[TreeCount] = field(default_factory=list)


@dataclass
class Report:
    findings: list[Finding]
    snapshot: Snapshot

    def has(self, code: str) -> bool:
        return any(item.code == code for item in self.findings)

    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "error"]


def _norm(name: str) -> str:
    return name.strip().lstrip("/").lower()


def watched_containers(names: Iterable[str]) -> list[str]:
    found: list[str] = []
    for name in names:
        short = _norm(name)
        if any(token in short for token in WATCH_NAMES):
            found.append(name.lstrip("/"))
    return found


def tree_count(snapshot: Snapshot, path: str) -> TreeCount:
    for tree in snapshot.trees:
        if tree.path.rstrip("/") == path.rstrip("/"):
            return tree
    return TreeCount(path=path, files=0, exists=False)


def mounts_for(snapshot: Snapshot, name_part: str) -> list[Mount]:
    needle = name_part.lower()
    return [mount for mount in snapshot.mounts if needle in mount.container.lower()]


def count_comic_files(root: Path, limit: int = 50_000) -> int:
    if not root.exists():
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            if Path(filename).suffix.lower() in COMIC_EXTS:
                total += 1
                if total >= limit:
                    return total
    return total


def mounts_from_inspect(payload: object) -> list[Mount]:
    items = payload if isinstance(payload, list) else [payload]
    mounts: list[Mount] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").lstrip("/")
        for raw in item.get("Mounts") or []:
            if not isinstance(raw, dict):
                continue
            mounts.append(
                Mount(
                    container=name,
                    destination=str(raw.get("Destination") or ""),
                    source=str(raw.get("Source") or ""),
                )
            )
    return mounts


def diagnose(snapshot: Snapshot) -> Report:
    findings: list[Finding] = []
    names = {_norm(name) for name in snapshot.containers}
    book = tree_count(snapshot, HOST_BOOK)
    manga = tree_count(snapshot, HOST_MANGA)
    comics = tree_count(snapshot, HOST_COMICS)
    omnibus_data = tree_count(snapshot, HOST_OMNIBUS_DATA)
    bleach = tree_count(snapshot, HOST_BLEACH)
    kapowarr_present = any("kapowarr" in name for name in names)

    if not kapowarr_present:
        readers = [
            name
            for name in snapshot.containers
            if any(token in _norm(name) for token in ("komga", "omnibus", "suwayomi", "kumiho", "kavita"))
        ]
        extra = (
            f" Readers already on this box: {', '.join(readers)}."
            if readers
            else " Komga / Omnibus / Suwayomi were not in the snapshot either."
        )
        findings.append(
            Finding(
                code="kapowarr_not_running",
                severity="error",
                title="Kapowarr is not running",
                detail=(
                    "There is no kapowarr container, so it cannot show any of the collection. "
                    "Kapowarr is a ComicVine grabber, not the library you already use to read files."
                    + extra
                ),
            )
        )

    if book.files or manga.files or comics.files:
        parts = []
        if manga.files:
            parts.append(f"{manga.files} under {HOST_MANGA}")
        if comics.files:
            parts.append(f"{comics.files} under {HOST_COMICS}")
        leftover = max(book.files - manga.files - comics.files, 0)
        if leftover:
            parts.append(f"{leftover} elsewhere under {HOST_BOOK}")
        findings.append(
            Finding(
                code="collection_is_split",
                severity="warning",
                title="The collection is split across folders",
                detail=(
                    "Komga can attach each folder as its own library. Kapowarr cannot. "
                    "It only sees files inside the root folder you add in Settings, "
                    "and that root must be a container path such as /comics. "
                    + ("Counted: " + "; ".join(parts) + "." if parts else "")
                ),
            )
        )

    if manga.files and comics.exists and comics.files < manga.files:
        findings.append(
            Finding(
                code="manga_dwarfs_comics",
                severity="warning",
                title="Most of the collection is manga, not western comics",
                detail=(
                    f"{manga.files} readable files sit in the manga tree versus {comics.files} in comics. "
                    "Kapowarr matches through ComicVine. Manga from Suwayomi / Tranga, and most BD française, "
                    "will not become volumes even when the files are on disk."
                ),
            )
        )

    if omnibus_data.exists and omnibus_data.files == 0 and (book.files or manga.files or comics.files):
        findings.append(
            Finding(
                code="empty_placeholder_share",
                severity="error",
                title="Omnibus /data is an empty placeholder share",
                detail=(
                    f"{HOST_OMNIBUS_DATA} is empty, but the real files are under {HOST_BOOK}. "
                    "If Kapowarr or Omnibus was pointed at /data/comics or /data/manga, the UI looks empty "
                    "even though Komga can still see /books."
                ),
            )
        )

    for mount in mounts_for(snapshot, "omnibus"):
        if mount.destination.rstrip("/") == "/data" and HOST_OMNIBUS_DATA in mount.source:
            findings.append(
                Finding(
                    code="omnibus_data_wrong_share",
                    severity="error",
                    title="Omnibus /data is not the book share",
                    detail=(
                        f"{mount.container} mounts {mount.source} at {mount.destination}. "
                        "That share is the empty placeholder. The unified library is mounted at /books "
                        f"from {HOST_BOOK}. Smart Match then returns Unauthorized path for anything under /books."
                    ),
                )
            )
        if mount.destination.rstrip("/") == "/manga" and "animation serie" in mount.source:
            findings.append(
                Finding(
                    code="stale_bleach_mount",
                    severity="warning",
                    title="Omnibus still mounts the old Bleach tree",
                    detail=(
                        f"{mount.container} maps {mount.source} to /manga. "
                        "Those files were folded into the unified manga folder. Leave this mount and "
                        "Smart Match / Kapowarr imports keep looking at a leftover path."
                    ),
                )
            )
        if mount.destination.rstrip("/") == "/books" and HOST_BOOK in mount.source:
            findings.append(
                Finding(
                    code="real_library_at_books",
                    severity="info",
                    title="The real library is the /books mount",
                    detail=(
                        f"{mount.container} already sees the collection at {mount.destination} "
                        f"({mount.source}). Point Kapowarr at /comics -> {HOST_COMICS} "
                        f"and keep manga on {HOST_MANGA} for Komga / Suwayomi."
                    ),
                )
            )

    kapowarr_mounts = mounts_for(snapshot, "kapowarr")
    comics_roots = [
        mount
        for mount in kapowarr_mounts
        if mount.destination.rstrip("/") in {"/comics", "/comics-2", "/manga", "/books"}
    ]
    if kapowarr_present and not comics_roots:
        findings.append(
            Finding(
                code="kapowarr_no_root_mount",
                severity="error",
                title="Kapowarr has no comics root mounted",
                detail=(
                    "The Kapowarr UI root folder must be the container path (/comics), and that path "
                    f"must map to {HOST_COMICS} on Unraid. A host path typed into the UI will look empty."
                ),
            )
        )

    for mount in comics_roots:
        source_tree = tree_count(snapshot, mount.source)
        if mount.source.rstrip("/") == HOST_OMNIBUS_DATA or mount.source.startswith(HOST_OMNIBUS_DATA + "/"):
            findings.append(
                Finding(
                    code="kapowarr_points_at_empty_share",
                    severity="error",
                    title="Kapowarr root points at the empty Omnibus share",
                    detail=(
                        f"Kapowarr mounts {mount.source} as {mount.destination}. "
                        f"Move that bind to {HOST_COMICS} and add /comics as the root folder in the UI."
                    ),
                )
            )
        elif source_tree.exists and source_tree.files == 0:
            findings.append(
                Finding(
                    code="kapowarr_empty_root",
                    severity="error",
                    title="Kapowarr root folder has no comic files",
                    detail=(
                        f"{mount.destination} -> {mount.source} exists but has 0 cbz/cbr/epub files. "
                        f"The files live under {HOST_BOOK}."
                    ),
                )
            )
        if mount.destination.rstrip("/") == "/comics" and mount.source.rstrip("/") == HOST_COMICS and manga.files:
            findings.append(
                Finding(
                    code="kapowarr_comics_only",
                    severity="warning",
                    title="Kapowarr is only looking at the comics folder",
                    detail=(
                        f"That is correct for western comics, but it will never list the {manga.files} manga files. "
                        "Do not add /manga as a Kapowarr root and then Import and Rename — that would move "
                        "Suwayomi / Tranga files out from under Komga."
                    ),
                )
            )
        if mount.destination.startswith("/mnt/user"):
            findings.append(
                Finding(
                    code="kapowarr_host_path_in_container",
                    severity="error",
                    title="Kapowarr was given a host path inside the container",
                    detail=(
                        f"Destination {mount.destination} is an Unraid host path. Inside Docker that folder "
                        "does not exist. Map the share to /comics and use /comics in Settings → Root Folders."
                    ),
                )
            )

    if bleach.exists and bleach.files:
        findings.append(
            Finding(
                code="leftover_bleach_tree",
                severity="warning",
                title="Files still sit in the old Bleach path",
                detail=(
                    f"{bleach.files} files remain under {HOST_BLEACH}. "
                    "Komga / Kapowarr will miss them unless that tree is merged into "
                    f"{HOST_MANGA} or added as its own library."
                ),
            )
        )

    findings.append(
        Finding(
            code="kapowarr_import_rules",
            severity="info",
            title="Kapowarr hides files that fail Library Import",
            detail=(
                "Even with the right mount, Kapowarr is not a folder browser. Library Import only lists "
                "files that sit in a subfolder of a root, then keeps only ComicVine matches. "
                "Unmatched files, the English-only checkbox, a low 'Max folders scanned' value, and a "
                "ComicVine rate limit all make the library look smaller than Komga. "
                "Prefer Import, never Import and Rename, on a folder Komga already reads."
            ),
        )
    )

    return Report(findings=findings, snapshot=snapshot)


def snapshot_from_dict(raw: dict) -> Snapshot:
    return Snapshot(
        containers=list(raw.get("containers") or []),
        mounts=[Mount(**item) for item in raw.get("mounts") or []],
        trees=[TreeCount(**item) for item in raw.get("trees") or []],
    )


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout


def live_snapshot(trees: Iterable[str] = DEFAULT_TREES) -> Snapshot:
    names = [
        line.strip().lstrip("/")
        for line in _run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines()
        if line.strip()
    ]
    watched = watched_containers(names)
    mounts: list[Mount] = []
    if watched:
        payload = json.loads(_run(["docker", "inspect", *watched]))
        mounts = mounts_from_inspect(payload)
    counts: list[TreeCount] = []
    for path in trees:
        root = Path(path)
        exists = root.exists()
        counts.append(TreeCount(path=path, files=count_comic_files(root) if exists else 0, exists=exists))
    return Snapshot(containers=watched, mounts=mounts, trees=counts)


def render(report: Report) -> str:
    lines = ["Kapowarr / comic visibility", ""]
    if not report.findings:
        lines.append("No findings.")
        return "\n".join(lines)
    for item in report.findings:
        mark = {"error": "ERROR", "warning": "WARN", "info": "INFO"}.get(item.severity, item.severity.upper())
        lines.append(f"[{mark}] {item.title}")
        lines.append(f"  {item.detail}")
        lines.append("")
    lines.append("Containers: " + (", ".join(report.snapshot.containers) or "(none)"))
    if report.snapshot.trees:
        lines.append("File counts (cbz/cbr/epub/pdf/zip):")
        for tree in report.snapshot.trees:
            state = f"{tree.files} files" if tree.exists else "missing"
            lines.append(f"  {tree.path}: {state}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose why Kapowarr does not see the whole collection")
    parser.add_argument("--fixture", type=Path, help="JSON snapshot instead of live docker/disk")
    parser.add_argument("--json", action="store_true", help="Print machine-readable findings")
    args = parser.parse_args(argv)

    if args.fixture:
        snapshot = snapshot_from_dict(json.loads(args.fixture.read_text()))
    else:
        if not Path("/mnt/user").exists() and not args.fixture:
            print(
                "This check wants Unraid paths under /mnt/user. "
                "On the cloud agent, replay the last snapshot:\n"
                "  python3 scripts/comics_visibility.py --fixture scripts/tests/fixtures/leroux-comics.json",
                file=sys.stderr,
            )
        try:
            snapshot = live_snapshot()
        except FileNotFoundError:
            print("docker is not available. Pass --fixture to analyze a saved snapshot.", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"Could not inspect docker: {exc}", file=sys.stderr)
            return 2

    report = diagnose(snapshot)
    if args.json:
        payload = {
            "findings": [asdict(item) for item in report.findings],
            "snapshot": {
                "containers": report.snapshot.containers,
                "mounts": [asdict(item) for item in report.snapshot.mounts],
                "trees": [asdict(item) for item in report.snapshot.trees],
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render(report), end="")
    return 1 if report.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
