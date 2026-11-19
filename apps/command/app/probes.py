from __future__ import annotations

import time

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.mautic import credentials_work as mautic_auth
from app.postiz import credentials_work as postiz_auth


def _get(url: str) -> tuple[bool, str, int]:
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.probe_timeout, follow_redirects=True) as client:
            response = client.get(url)
        ok = response.status_code < 500
        detail = f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        ok = False
        detail = exc.__class__.__name__
    elapsed = round((time.perf_counter() - started) * 1000)
    return ok, detail, elapsed


def service_status(db: Session) -> list[dict]:
    rows = []
    checks = [
        ("n8n", f"{settings.n8n_internal_url.rstrip('/')}/healthz", None),
        ("mautic", settings.mautic_internal_url, mautic_auth),
        ("postiz", f"{settings.postiz_internal_url.rstrip('/')}/", postiz_auth),
    ]
    for name, url, auth in checks:
        reachable, detail, elapsed = _get(url)
        authenticated = None
        if reachable and auth is not None:
            authenticated, auth_detail = auth(db)
            if authenticated is not None:
                detail = auth_detail
        rows.append(
            {
                "service": name,
                "reachable": reachable,
                "authenticated": authenticated,
                "detail": detail,
                "ms": elapsed,
            }
        )
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        reachable, detail = True, "command database answered"
    except Exception as exc:  # noqa: BLE001 - the status row is the error
        reachable, detail = False, exc.__class__.__name__
    rows.append(
        {
            "service": "postgres",
            "reachable": reachable,
            "authenticated": None,
            "detail": detail,
            "ms": round((time.perf_counter() - started) * 1000),
        }
    )
    return rows
