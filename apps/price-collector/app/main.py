from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.browser import login_active, profile_ready, start_login, stop_login
from app.scan import run_scan, scan_running
from app.settings import settings
from app.suppliers import SUPPLIERS, supplier_by_slug
from app.worker import worker


def _scheduled_scan() -> None:
    worker.call(run_scan, timeout=7200)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.timezone))
    scheduler.add_job(
        _scheduled_scan,
        CronTrigger(hour=settings.scan_hour, minute=settings.scan_minute, timezone=settings.timezone),
        id="nightly-scan",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Restaurant price collector", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "price-collector",
        "scan_running": scan_running(),
        "login": login_active(),
        "when": f"{settings.scan_hour:02d}:{settings.scan_minute:02d} {settings.timezone}",
    }


@app.get("/suppliers")
def suppliers():
    rows = []
    for source in SUPPLIERS:
        rows.append(
            {
                **source,
                "profile": profile_ready(source["slug"]),
                "login_open": login_active() == source["slug"],
            }
        )
    return {"suppliers": rows}


class LoginIn(BaseModel):
    slug: str


def _browser_result(result, error_status: int = 500):
    if not isinstance(result, dict):
        return JSONResponse({"ok": False, "error": "Could not talk to Chromium."}, 500)
    if not result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": str(result.get("error") or "Could not open Chromium.")[:400]},
            error_status,
        )
    return result


@app.post("/login/start")
def login_start(body: LoginIn):
    if scan_running():
        return JSONResponse({"ok": False, "error": "Nightly scan is running. Try again when it finishes."}, 409)
    if supplier_by_slug(body.slug) is None:
        return JSONResponse({"ok": False, "error": "unknown supplier"}, 404)
    return _browser_result(worker.call(start_login, body.slug, timeout=90))


@app.post("/login/finish")
def login_finish():
    return _browser_result(worker.call(stop_login, timeout=60))


@app.post("/jobs/scan")
def jobs_scan():
    if scan_running() or login_active():
        return JSONResponse({"ok": False, "error": "browser is busy"}, 409)

    def _run():
        worker.call(run_scan, timeout=7200)

    import threading

    threading.Thread(target=_run, daemon=True, name="scan-job").start()
    return {"ok": True, "started": True, "at": datetime.now().isoformat()}
