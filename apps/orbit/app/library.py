"""Library board: films, series, grabs, screen — not a junk drawer."""

from __future__ import annotations

import httpx

from app.catalog import library_apps
from app.files import _walk_limited, recent
from app.settings import settings

TIMEOUT = httpx.Timeout(2.0, connect=1.0)


def _probe(url: str) -> str:
    if not url:
        return "unlinked"
    try:
        with httpx.Client(timeout=TIMEOUT, verify=False, follow_redirects=True) as client:
            response = client.get(url)
        if response.status_code < 500:
            return "up"
        return "down"
    except httpx.HTTPError:
        return "down"


def _folder_stats(needles: tuple[str, ...]) -> dict:
    mapping = settings.root_map()
    for label, path in mapping.items():
        hay = f"{label} {path}".lower()
        if any(needle in hay for needle in needles):
            videos = 0
            files = 0
            if path.exists():
                try:
                    for child in _walk_limited(path, max_depth=4, max_files=800):
                        files += 1
                        if child.suffix.lower() in {".mp4", ".mkv", ".avi", ".mov", ".m4v"}:
                            videos += 1
                except OSError:
                    pass
            return {"root": label, "path": str(path), "files": files, "videos": videos, "exists": path.exists()}
    return {"root": "", "path": "", "files": 0, "videos": 0, "exists": False}


def _arr_queue(url: str, api_key: str) -> list[dict]:
    if not url or not api_key:
        return []
    try:
        with httpx.Client(timeout=TIMEOUT, verify=False) as client:
            response = client.get(f"{url.rstrip('/')}/api/v3/queue", headers={"X-Api-Key": api_key})
        if response.status_code >= 400:
            return []
        records = response.json().get("records") or []
    except (httpx.HTTPError, ValueError):
        return []
    rows = []
    for rec in records[:8]:
        rows.append(
            {
                "title": rec.get("title") or rec.get("sourceTitle") or "Untitled",
                "state": rec.get("status") or rec.get("trackedDownloadState") or "",
                "kind": "film" if "movie" in rec else "series",
            }
        )
    return rows


def snapshot() -> dict:
    apps = []
    for app in library_apps():
        status = _probe(app["href"]) if app["linked"] else "unlinked"
        apps.append({**app, "status": status})
    films = _folder_stats(("film", "movie", "library", "media"))
    series = _folder_stats(("series", "tv", "show", "library", "media"))
    grabs = _folder_stats(("grab", "download", "torrent", "complete"))
    queue = _arr_queue(settings.radarr_url, settings.radarr_api_key)
    queue += _arr_queue(settings.sonarr_url, settings.sonarr_api_key)
    latest = recent(10)
    videos = [item for item in latest if item["kind"] == "video"]
    return {
        "apps": apps,
        "films": {**films, "label": "Films", "hint": "Radarr keeps the collection tidy"},
        "series": {**series, "label": "Series", "hint": "Sonarr watches the calendar"},
        "grabs": {**grabs, "label": "Grabs", "hint": "Active downloads and drop folders"},
        "screen": {
            "label": "Screen",
            "hint": "Jellyfin / Plex for playback",
            "href": settings.jellyfin_url,
            "linked": bool(settings.jellyfin_url),
        },
        "queue": queue,
        "recent": videos or latest[:6],
    }
