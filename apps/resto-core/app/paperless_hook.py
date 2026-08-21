from __future__ import annotations

import threading
import time

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import access_token_for
from app.sync import sync_paperless

WORKFLOW_NAME = "Resto cellar: new invoice"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_MIN_INTERVAL = 20.0
_lock = threading.Lock()
_last_sync = 0.0


def paperless_callback_url() -> str:
    return settings.resto_public_url.rstrip("/") + "/api/jobs/sync-paperless"


def sync_paperless_now(db: Session, max_pages: int = 3) -> dict:
    global _last_sync
    with _lock:
        now = time.monotonic()
        if now - _last_sync < _MIN_INTERVAL:
            return {"status": "ok", "throttled": True}
        _last_sync = now
    return sync_paperless(db, max_pages=max_pages)


def _workflow_payload() -> dict:
    return {
        "name": WORKFLOW_NAME,
        "order": 99,
        "enabled": True,
        "triggers": [
            {"type": 2, "sources": [1, 2, 3, 4]},  # document added: folder, API, mail, UI
            {"type": 3, "sources": [1, 2, 3, 4]},  # document updated (OCR finished)
        ],
        "actions": [
            {
                "type": 4,
                "webhook": {
                    "url": paperless_callback_url(),
                    "use_params": False,
                    "as_json": True,
                    "body": "{}",
                    "headers": {
                        "X-API-Key": settings.resto_api_key,
                        "Content-Type": "application/json",
                    },
                    "include_document": False,
                },
            }
        ],
    }


def ensure_paperless_sync_workflow(db: Session) -> dict:
    token = access_token_for(db, "paperless")
    if not token:
        return {"status": "skipped", "reason": "not connected"}
    base = settings.paperless_base_url.rstrip("/")
    headers = {"Authorization": f"Token {token}"}
    payload = _workflow_payload()
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            listing = client.get(f"{base}/api/workflows/", headers=headers, params={"page_size": 100})
            if listing.status_code == 404:
                return {"status": "skipped", "reason": "workflows not available"}
            listing.raise_for_status()
            existing = next(
                (item for item in (listing.json().get("results") or []) if item.get("name") == WORKFLOW_NAME),
                None,
            )
            if existing:
                response = client.patch(
                    f"{base}/api/workflows/{existing['id']}/",
                    headers=headers,
                    json=payload,
                )
            else:
                response = client.post(f"{base}/api/workflows/", headers=headers, json=payload)
            if response.status_code >= 400:
                return {"status": "error", "error": response.text[:300]}
        return {"status": "ok", "updated": bool(existing)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
