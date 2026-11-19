from dataclasses import dataclass

import httpx


@dataclass
class Remote:
    ok: bool
    status_code: int
    payload: object
    detail: str


def interpret(response: httpx.Response) -> Remote:
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    detail = f"HTTP {response.status_code}"
    if response.status_code >= 400:
        message = ""
        if isinstance(payload, dict):
            raw = payload.get("error") or payload.get("detail") or payload.get("message") or payload.get("errors")
            if isinstance(raw, dict):
                raw = raw.get("message") or raw.get("status") or raw
            message = str(raw or "")
        if not message:
            message = (response.text or "")[:400]
        detail = message[:400] or detail
    ok = 200 <= response.status_code < 300
    return Remote(ok, response.status_code, payload, "OK" if ok else detail)
