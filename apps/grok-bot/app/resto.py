"""Ask resto-core how the restaurant is doing."""

from __future__ import annotations

import httpx

from app.settings import settings


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.resto_api_key}


def _url(path: str) -> str:
    return f"{settings.resto_url.rstrip('/')}{path}"


def _get(path: str, params: dict | None = None) -> dict:
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(_url(path), headers=_headers(), params=params)
    except httpx.HTTPError as exc:
        return {"error": f"Could not reach the cellar app: {str(exc)[:160]}"}
    if response.status_code == 401:
        return {"error": "The cellar app rejected the API key. Check RESTO_API_KEY."}
    if not response.is_success:
        return {"error": f"The cellar app answered {response.status_code}."}
    return response.json()


def _post(path: str, params: dict | None = None) -> dict:
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(_url(path), headers=_headers(), params=params)
    except httpx.HTTPError as exc:
        return {"error": f"Could not reach the cellar app: {str(exc)[:160]}"}
    if not response.is_success:
        return {"error": f"The cellar app answered {response.status_code}."}
    return response.json()


def restaurant_status() -> dict:
    return _get("/api/status")


def fridges() -> dict:
    return _get("/api/house")


def run_sync() -> dict:
    return _post("/api/jobs/sync-all")
