from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.remote import Remote, interpret
from app.vault import get_secret


def api_base(db: Session) -> str:
    saved = (get_secret(db, "mautic_api_base") or "").strip()
    return (saved or settings.mautic_internal_url).rstrip("/")


def _auth(db: Session) -> tuple[httpx.Auth | None, dict, str | None]:
    mode = (get_secret(db, "mautic_auth") or "basic").strip().lower()
    username = get_secret(db, "mautic_username") or ""
    password = get_secret(db, "mautic_password") or ""
    if not username or not password:
        return None, {}, "Mautic API credentials are not saved"
    if mode == "oauth2":
        base = api_base(db)
        try:
            with httpx.Client(timeout=20) as client:
                token_response = client.post(
                    f"{base}/oauth/v2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": username,
                        "client_secret": password,
                    },
                )
        except httpx.HTTPError as exc:
            return None, {}, exc.__class__.__name__
        parsed = interpret(token_response)
        if not parsed.ok or not isinstance(parsed.payload, dict) or not parsed.payload.get("access_token"):
            return None, {}, parsed.detail
        return None, {"Authorization": f"Bearer {parsed.payload['access_token']}"}, None
    return httpx.BasicAuth(username, password), {}, None


def request(db: Session, method: str, path: str, **kwargs) -> Remote:
    auth, headers, problem = _auth(db)
    if problem:
        return Remote(False, 0, None, problem)
    url = f"{api_base(db)}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.request(method, url, auth=auth, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def credentials_work(db: Session) -> tuple[bool | None, str]:
    if not (get_secret(db, "mautic_username") and get_secret(db, "mautic_password")):
        return None, "API credentials are not saved"
    result = request(db, "GET", "/api/contacts?limit=1")
    if result.ok:
        return True, "Mautic accepted the API credentials"
    return False, result.detail


def contact_total(payload: object) -> int | None:
    if not isinstance(payload, dict) or "total" not in payload:
        return None
    try:
        return int(payload["total"])
    except (TypeError, ValueError):
        return None


def segment_rows(payload: object) -> list[dict] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("segments")
    if raw is None:
        raw = payload.get("lists")
    if raw is None:
        return None
    rows: list = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    if not isinstance(raw, (dict, list)):
        return None
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = row.get("isPublished")
        cleaned.append(
            {
                "id": str(row.get("id") or ""),
                "name": row.get("name") or "Untitled",
                "published": bool(published) if published is not None else False,
            }
        )
    return [row for row in cleaned if row["id"] or row["name"]]


def campaign_rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("campaigns")
    rows: list = []
    if isinstance(raw, dict):
        rows = list(raw.values())
    elif isinstance(raw, list):
        rows = raw
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = row.get("isPublished")
        cleaned.append(
            {
                "id": str(row.get("id") or ""),
                "name": row.get("name") or "Untitled",
                "published": bool(published) if published is not None else False,
            }
        )
    return cleaned
