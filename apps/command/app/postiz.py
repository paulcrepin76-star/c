from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.remote import Remote, interpret
from app.vault import get_secret

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp", "image/tiff"}
VIDEO_TYPES = {"video/mp4"}


def api_root(db: Session) -> str:
    saved = (get_secret(db, "postiz_api_base") or "").strip()
    base = (saved or settings.postiz_internal_url).rstrip("/")
    if base.endswith("/api/public/v1"):
        return base
    return f"{base}/api/public/v1"


def _headers(db: Session) -> tuple[dict | None, str | None]:
    key = (get_secret(db, "postiz_api_key") or "").strip()
    if not key:
        return None, "Postiz public API key is not saved"
    return {"Authorization": key}, None


def request(db: Session, method: str, path: str, **kwargs) -> Remote:
    headers, problem = _headers(db)
    if problem:
        return Remote(False, 0, None, problem)
    extra = kwargs.pop("headers", {})
    try:
        with httpx.Client(timeout=60) as client:
            response = client.request(method, f"{api_root(db)}{path}", headers={**headers, **extra}, **kwargs)
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def credentials_work(db: Session) -> tuple[bool | None, str]:
    if not get_secret(db, "postiz_api_key"):
        return None, "Public API key is not saved"
    result = request(db, "GET", "/integrations")
    if result.ok:
        return True, "Postiz accepted the API key"
    return False, result.detail


def integration_rows(payload: object) -> list[dict]:
    raw = payload
    if isinstance(payload, dict):
        raw = payload.get("integrations") or payload.get("data") or payload
    if isinstance(raw, dict):
        raw = list(raw.values())
    rows = []
    if not isinstance(raw, list):
        return rows
    for row in raw:
        if not isinstance(row, dict):
            continue
        provider = row.get("providerIdentifier") or row.get("identifier") or row.get("provider") or ""
        rows.append(
            {
                "id": str(row.get("id") or ""),
                "provider": str(provider),
                "name": row.get("name") or provider or "Channel",
                "disabled": bool(row.get("disabled", False)),
            }
        )
    return [row for row in rows if row["id"]]


def map_remote_state(state: str | None) -> str:
    if state == "PUBLISHED":
        return "published"
    if state == "ERROR":
        return "error"
    if state == "DRAFT":
        return "draft"
    if state == "QUEUE":
        return "submitted"
    return "submitted"


def settings_for(provider: str) -> dict:
    if provider in {"instagram", "instagram-standalone"}:
        return {"__type": provider, "post_type": "post", "is_trial_reel": False, "collaborators": []}
    if provider == "tiktok":
        return {
            "__type": "tiktok",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "duet": False,
            "stitch": False,
            "comment": True,
            "autoAddMusic": "no",
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "video_made_with_ai": False,
            "content_posting_method": "DIRECT_POST",
        }
    if provider == "gmb":
        return {"__type": "gmb", "topicType": "STANDARD"}
    if provider == "facebook":
        return {"__type": "facebook"}
    return {"__type": provider}


def needs_video(provider: str) -> bool:
    return provider == "tiktok"


def needs_image(provider: str) -> bool:
    return provider in {"instagram", "instagram-standalone"}


def build_create_body(channels: list[dict], body: str, media: list[dict], scheduled_for: str, mode: str) -> dict:
    when = scheduled_for
    post_type = "schedule" if mode == "schedule" else "now"
    if post_type == "now":
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    posts = []
    for channel in channels:
        provider = channel.get("provider") or "facebook"
        posts.append(
            {
                "integration": {"id": channel["integration_id"]},
                "value": [{"content": body, "image": [{"id": item["id"], "path": item["path"]} for item in media]}],
                "settings": settings_for(provider),
            }
        )
    return {"type": post_type, "date": when, "shortLink": False, "tags": [], "posts": posts}


def upload_file(db: Session, filename: str, content_type: str, blob: bytes) -> Remote:
    return request(
        db,
        "POST",
        "/upload",
        files={"file": (filename, blob, content_type or "application/octet-stream")},
    )
