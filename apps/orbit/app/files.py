"""Browse, download, and organize files inside configured roots."""

from __future__ import annotations

import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.settings import settings

MAX_UPLOAD = 80 * 1024 * 1024
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}
AUDIO_EXT = {".mp3", ".flac", ".aac", ".wav", ".ogg", ".m4a"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".heic"}
DOC_EXT = {".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".xls", ".xlsx"}
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".7z", ".rar"}


def roots() -> list[dict]:
    rows = []
    for label, path in settings.root_map().items():
        exists = path.exists()
        count = 0
        if exists and path.is_dir():
            try:
                count = sum(1 for _ in path.iterdir())
            except OSError:
                count = 0
        rows.append({"id": label, "name": label, "path": str(path), "exists": exists, "count": count})
    return rows


def _root(label: str) -> Path:
    mapping = settings.root_map()
    if label not in mapping:
        raise HTTPException(404, "Unknown folder")
    path = mapping[label].resolve()
    if not path.exists():
        raise HTTPException(404, "Folder is not mounted")
    return path


def _safe(label: str, rel: str) -> Path:
    root = _root(label)
    target = (root / (rel or "")).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, "Path is outside the allowed folder")
    return target


def _kind(path: Path) -> str:
    if path.is_dir():
        return "folder"
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext in DOC_EXT:
        return "doc"
    if ext in ARCHIVE_EXT:
        return "archive"
    return "file"


def _entry(label: str, path: Path, root: Path) -> dict:
    rel = "" if path == root else str(path.relative_to(root))
    stat = path.stat()
    return {
        "name": path.name,
        "path": rel,
        "root": label,
        "kind": _kind(path),
        "size": 0 if path.is_dir() else stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def listing(label: str, rel: str = "") -> dict:
    root = _root(label)
    current = _safe(label, rel)
    if not current.exists():
        raise HTTPException(404, "Not found")
    if current.is_file():
        return {"root": label, "path": rel, "kind": "file", "entry": _entry(label, current, root)}
    items: list[dict] = []
    try:
        children = list(current.iterdir())
    except OSError as exc:
        raise HTTPException(403, f"Cannot read folder: {exc}") from exc
    children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            items.append(_entry(label, child, root))
        except OSError:
            continue
    crumbs = [{"name": label, "path": ""}]
    if rel:
        parts = Path(rel).parts
        acc = []
        for part in parts:
            acc.append(part)
            crumbs.append({"name": part, "path": "/".join(acc)})
    return {"root": label, "path": rel, "kind": "folder", "crumbs": crumbs, "items": items}


def download(label: str, rel: str) -> FileResponse:
    path = _safe(label, rel)
    if not path.is_file():
        raise HTTPException(400, "Not a file")
    media, _ = mimetypes.guess_type(path.name)
    return FileResponse(path, filename=path.name, media_type=media or "application/octet-stream")


def mkdir(label: str, rel: str, name: str) -> dict:
    name = (name or "").strip()
    if not name or "/" in name or name in {".", ".."}:
        raise HTTPException(400, "Bad folder name")
    parent = _safe(label, rel)
    if not parent.is_dir():
        raise HTTPException(400, "Parent is not a folder")
    target = (parent / name).resolve()
    if parent not in target.parents:
        raise HTTPException(400, "Path is outside the allowed folder")
    try:
        target.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise HTTPException(409, "Already exists") from exc
    except OSError as exc:
        raise HTTPException(403, f"Cannot create folder: {exc}") from exc
    return listing(label, rel)


async def upload(label: str, rel: str, file: UploadFile) -> dict:
    filename = Path(file.filename or "upload").name
    if not filename or filename.startswith("."):
        raise HTTPException(400, "Bad file name")
    parent = _safe(label, rel)
    if not parent.is_dir():
        raise HTTPException(400, "Parent is not a folder")
    dest = (parent / filename).resolve()
    if parent not in dest.parents:
        raise HTTPException(400, "Path is outside the allowed folder")
    size = 0
    try:
        with dest.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD:
                    handle.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, "File is too large")
                handle.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(403, f"Cannot write file: {exc}") from exc
    return listing(label, rel)


def remove(label: str, rel: str) -> dict:
    if not rel:
        raise HTTPException(400, "Cannot delete a root folder")
    path = _safe(label, rel)
    parent_rel = str(Path(rel).parent) if Path(rel).parent.as_posix() != "." else ""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        raise HTTPException(403, f"Cannot delete: {exc}") from exc
    return listing(label, parent_rel)


def _walk_limited(root: Path, max_depth: int = 3, max_files: int = 250):
    try:
        base = root.resolve()
    except OSError:
        return
    stack = [(base, 0)]
    seen = 0
    while stack and seen < max_files:
        current, depth = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            try:
                if child.is_dir() and depth < max_depth:
                    stack.append((child, depth + 1))
                elif child.is_file():
                    seen += 1
                    yield child
                    if seen >= max_files:
                        return
            except OSError:
                continue


def recent(limit: int = 8) -> list[dict]:
    found: list[tuple[float, dict]] = []
    for label, root in settings.root_map().items():
        if not root.exists():
            continue
        resolved = root.resolve()
        for path in _walk_limited(resolved):
            try:
                found.append((path.stat().st_mtime, _entry(label, path, resolved)))
            except OSError:
                continue
    found.sort(key=lambda row: row[0], reverse=True)
    return [row[1] for row in found[:limit]]
