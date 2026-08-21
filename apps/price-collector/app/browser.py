from __future__ import annotations

import fcntl
from pathlib import Path

from app.extract import classify_wall
from app.settings import settings
from app.suppliers import supplier_by_slug

_LOGIN = {"slug": None, "playwright": None, "context": None}


def data_root() -> Path:
    root = Path(settings.data_dir)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "locks").mkdir(parents=True, exist_ok=True)
    return root


def profile_dir(slug: str) -> Path:
    path = data_root() / "profiles" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_ready(slug: str) -> bool:
    path = profile_dir(slug)
    return any(path.iterdir())


def _clear_stale_profile_locks(slug: str) -> None:
    path = profile_dir(slug)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock = path / name
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def lock_path() -> Path:
    return data_root() / "locks" / "browser.lock"


class BrowserLock:
    def __init__(self):
        self._fh = None

    def acquire(self, blocking: bool = False) -> bool:
        self._fh = open(lock_path(), "w")
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(self._fh.fileno(), flags)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def _launch_kwargs(headless: bool) -> dict:
    return {
        "headless": headless,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
        "viewport": {"width": 1280, "height": 800},
        "ignore_https_errors": True,
    }


def inspect_page(page) -> str | None:
    url = page.url or ""
    html = ""
    text = ""
    try:
        html = page.content()[:12000]
    except Exception:  # noqa: BLE001
        html = ""
    try:
        text = page.inner_text("body")[:4000]
    except Exception:  # noqa: BLE001
        text = ""
    return classify_wall(url, html, text)


def start_login(slug: str) -> dict:
    source = supplier_by_slug(slug)
    if source is None:
        return {"ok": False, "error": "unknown supplier"}
    stop_login()
    _clear_stale_profile_locks(slug)
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir(slug)),
            **_launch_kwargs(headless=False),
        )
    except Exception as exc:  # noqa: BLE001
        try:
            playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"Could not open Chromium: {exc}"[:400]}

    page = context.pages[0] if context.pages else context.new_page()
    _LOGIN.update({"slug": slug, "playwright": playwright, "context": context})
    warning = ""
    try:
        page.goto(source["login_url"], wait_until="domcontentloaded", timeout=25000)
    except Exception as exc:  # noqa: BLE001
        warning = str(exc)[:200]
    result = {"ok": True, "slug": slug, "label": source["label"], "url": source["login_url"]}
    if warning:
        result["warning"] = warning
    return result


def stop_login() -> dict:
    slug = _LOGIN.get("slug")
    context = _LOGIN.get("context")
    playwright = _LOGIN.get("playwright")
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
    _LOGIN.update({"slug": None, "playwright": None, "context": None})
    return {"ok": True, "slug": slug, "profile": profile_ready(slug) if slug else False}


def login_active() -> str | None:
    return _LOGIN.get("slug")


def open_scan_context(slug: str):
    from playwright.sync_api import sync_playwright

    _clear_stale_profile_locks(slug)
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        str(profile_dir(slug)),
        **_launch_kwargs(headless=True),
    )
    return playwright, context
