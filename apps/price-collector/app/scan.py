from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from app.browser import BrowserLock, inspect_page, open_scan_context, profile_ready
from app.extract import matches_watch, products_from_html, search_url, walk_products
from app.settings import settings
from app.suppliers import SUPPLIERS

_running = False


def cellar_headers() -> dict:
    return {"X-API-Key": settings.resto_api_key, "Content-Type": "application/json"}


def cellar_get(path: str) -> dict:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{settings.resto_url}{path}", headers=cellar_headers())
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def cellar_post(path: str, payload: dict) -> dict:
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{settings.resto_url}{path}", headers=cellar_headers(), json=payload)
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "recorded": 0}


def collect_from_page(page, url: str) -> tuple[str | None, list[dict]]:
    bag: list[dict] = []

    def on_response(response):
        try:
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype or not response.ok:
                return
            body = response.json()
            bag.extend(walk_products(body))
        except Exception:  # noqa: BLE001
            return

    page.on("response", on_response)
    page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
    page.wait_for_timeout(1800)
    blocked = inspect_page(page)
    html_items = products_from_html(page.content())
    page.remove_listener("response", on_response)
    items = bag + html_items
    seen: set[str] = set()
    unique = []
    for item in items:
        key = f"{item.get('sku') or item.get('name')}|{item.get('price')}"
        if key in seen:
            continue
        seen.add(key)
        if not item.get("url"):
            item["url"] = page.url
        unique.append(item)
    return blocked, unique


def queries_for(source: dict, product: dict) -> list[str]:
    sku = (product.get("supplier_skus") or {}).get(source["label"]) or ""
    url = (product.get("supplier_urls") or {}).get(source["label"]) or ""
    found = []
    if url:
        found.append(url)
    if sku:
        found.append(search_url(source, sku))
    name = product.get("name") or ""
    if name:
        found.append(search_url(source, name))
    # de-dupe preserve order
    out = []
    for item in found:
        if item and item not in out:
            out.append(item)
    return out[:2]


def scan_supplier(source: dict, products: list[dict]) -> dict:
    result = {
        "slug": source["slug"],
        "label": source["label"],
        "status": "ok",
        "checked": 0,
        "updated": 0,
        "unavailable": 0,
        "error": "",
    }
    if source.get("needs_login") and not profile_ready(source["slug"]):
        result["status"] = "needs_reauth"
        result["error"] = "never_logged_in"
        cellar_post(
            "/api/collector/auth",
            {"slug": source["slug"], "status": "never_logged_in", "error": "Open Prices and log in once in the Unraid browser."},
        )
        return result
    playwright = None
    context = None
    try:
        playwright, context = open_scan_context(source["slug"])
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(source["home_url"], wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        page.wait_for_timeout(1200)
        blocked = inspect_page(page)
        if blocked:
            result["status"] = "needs_reauth"
            result["error"] = blocked
            cellar_post(
                "/api/collector/auth",
                {"slug": source["slug"], "status": "needs_reauth", "error": blocked},
            )
            return result
        cellar_post("/api/collector/auth", {"slug": source["slug"], "status": "ready", "error": ""})
        for product in products[: settings.per_supplier_limit]:
            urls = queries_for(source, product)
            found = []
            blocked = None
            for url in urls:
                blocked, items = collect_from_page(page, url)
                if blocked:
                    break
                wanted = [item for item in items if matches_watch(item, product.get("needles") or [])]
                found.extend(wanted or items[:3])
                time.sleep(settings.pause_seconds)
            result["checked"] += 1
            if blocked:
                result["status"] = "needs_reauth"
                result["error"] = blocked
                cellar_post(
                    "/api/collector/auth",
                    {"slug": source["slug"], "status": "needs_reauth", "error": blocked},
                )
                break
            if not found:
                result["unavailable"] += 1
                continue
            posted = cellar_post(
                "/api/prices/collect",
                {
                    "supplier": source["label"],
                    "source": "auth_browser" if source.get("needs_login") else "playwright",
                    "items": found[:8],
                },
            )
            result["updated"] += int(posted.get("recorded") or 0)
            if int(posted.get("recorded") or 0) == 0:
                result["unavailable"] += 1
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = str(exc)[:240]
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:  # noqa: BLE001
                pass
    return result


def run_scan() -> dict:
    global _running
    if _running:
        return {"ok": False, "error": "scan already running"}
    if login_busy():
        return {"ok": False, "error": "login window is open"}
    lock = BrowserLock()
    if not lock.acquire(blocking=False):
        return {"ok": False, "error": "browser is busy"}
    _running = True
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    sources = []
    try:
        watch = cellar_get("/api/prices/watch?cap=200")
        products = watch.get("products") or []
        for source in SUPPLIERS:
            sources.append(scan_supplier(source, products))
        checked = sum(row["checked"] for row in sources)
        updated = sum(row["updated"] for row in sources)
        unavailable = sum(row["unavailable"] for row in sources)
        needs = [row["slug"] for row in sources if row["status"] == "needs_reauth"]
        payload = {
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "checked": checked,
            "updated": updated,
            "unchanged": max(checked - updated - unavailable, 0),
            "unavailable": unavailable,
            "needs_reauth": needs,
            "sources": sources,
        }
        cellar_post("/api/collector/runs", payload)
        return {"ok": True, **payload}
    finally:
        _running = False
        lock.release()


def login_busy() -> bool:
    from app.browser import login_active

    return bool(login_active())


def scan_running() -> bool:
    return _running
