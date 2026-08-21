from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import (
    access_token_for,
    disconnect,
    extra_dict,
    get_connection,
    mark_connected,
    mark_error,
    set_extra,
    square_app_creds,
    square_host,
    strip_auth_prefix,
)
from app.db import get_db
from app.models import Invoice, Supplier
from app.sync import sync_all
from app.vendors import VENDORS, vendor_by_slug
from app.web import render

router = APIRouter()
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
SQUARE_SCOPES = "ORDERS_READ ITEMS_READ MERCHANT_PROFILE_READ PAYMENTS_READ"
SYSTEM_NAMES = {"square", "mealie", "paperless"}
VENDOR_SLUGS = {vendor["slug"] for vendor in VENDORS}


def _vendor_cards(db: Session) -> list[dict]:
    cards = []
    for vendor in VENDORS:
        connection = get_connection(db, vendor["slug"])
        supplier = db.query(Supplier).filter(Supplier.name == vendor["label"]).first()
        filed = 0
        if supplier:
            filed = db.query(Invoice).filter(Invoice.supplier_id == supplier.id).count()
        cards.append({**vendor, "connection": connection, "filed_count": filed, "login": extra_dict(connection).get("login", "")})
    return cards


def _ensure_paperless_correspondent(db: Session, vendor: dict) -> None:
    token = access_token_for(db, "paperless")
    if not token:
        return
    base = settings.paperless_base_url.rstrip("/")
    headers = {"Authorization": f"Token {token}"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            listing = client.get(f"{base}/api/correspondents/", headers=headers, params={"page_size": 200})
            if listing.status_code != 200:
                return
            names = {str(item.get("name") or "").lower() for item in listing.json().get("results") or []}
            if vendor["label"].lower() in names:
                return
            client.post(f"{base}/api/correspondents/", headers=headers, json={"name": vendor["label"]})
    except Exception:  # noqa: BLE001
        return


def _flash(request: Request, ok: str = "", err: str = "") -> None:
    if ok:
        request.session["flash_ok"] = ok
    if err:
        request.session["flash_err"] = err


def _pop_flash(request: Request) -> tuple[str, str]:
    ok = request.session.pop("flash_ok", "")
    err = request.session.pop("flash_err", "")
    return ok, err


def _redirect_connect() -> RedirectResponse:
    return RedirectResponse("/connect", status_code=303)


def square_callback_url() -> str:
    return settings.resto_public_url.rstrip("/") + "/connect/square/callback"


@router.get("/connect")
def connect_page(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    square = get_connection(db, "square")
    mealie = get_connection(db, "mealie")
    paperless = get_connection(db, "paperless")
    app_id, app_secret = square_app_creds(db)
    extra = extra_dict(square)
    return render(
        request,
        "connect.html",
        page="connect",
        flash_ok=ok,
        flash_err=err,
        square=square,
        mealie=mealie,
        paperless=paperless,
        square_app_ready=bool(app_id and app_secret),
        square_location=extra.get("location_id") or settings.square_location_id,
        square_callback=square_callback_url(),
        mealie_url=settings.mealie_base_url,
        paperless_url=settings.paperless_public_url or settings.paperless_base_url,
        vendors=_vendor_cards(db),
    )


@router.post("/connect/square/app")
def save_square_app(
    request: Request,
    application_id: str = Form(""),
    application_secret: str = Form(""),
    db: Session = Depends(get_db),
):
    row = get_connection(db, "square")
    set_extra(
        row,
        application_id=strip_auth_prefix(application_id),
        application_secret=application_secret.strip(),
    )
    db.commit()
    _flash(request, ok="Square app saved. Now click Sign in with Square.")
    return _redirect_connect()


@router.get("/connect/square")
def start_square_oauth(request: Request, db: Session = Depends(get_db)):
    app_id, app_secret = square_app_creds(db)
    if not app_id or not app_secret:
        _flash(request, err="Save the Square Application ID and Secret first, or paste an access token below.")
        return _redirect_connect()
    state = secrets.token_urlsafe(24)
    request.session["square_oauth_state"] = state
    query = urlencode(
        {
            "client_id": app_id,
            "scope": SQUARE_SCOPES,
            "session": "false",
            "state": state,
            "redirect_uri": square_callback_url(),
        }
    )
    return RedirectResponse(f"{square_host()}/oauth2/authorize?{query}", status_code=302)


@router.get("/connect/square/callback")
def square_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        _flash(request, err=f"Square said: {error}")
        return _redirect_connect()
    expected = request.session.pop("square_oauth_state", "")
    if not code or not state or state != expected:
        _flash(request, err="Square login was cancelled or expired. Try Connect again.")
        return _redirect_connect()
    app_id, app_secret = square_app_creds(db)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            token_resp = client.post(
                f"{square_host()}/oauth2/token",
                json={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": square_callback_url(),
                },
            )
            token_resp.raise_for_status()
            payload = token_resp.json()
            access = payload.get("access_token") or ""
            refresh = payload.get("refresh_token") or ""
            if not access:
                raise RuntimeError("Square did not return an access token")
            loc = client.get(
                f"{square_host()}/v2/locations",
                headers={"Authorization": f"Bearer {access}", "Square-Version": "2025-01-23"},
            )
            loc.raise_for_status()
            locations = loc.json().get("locations") or []
            active = [item for item in locations if str(item.get("status", "")).upper() == "ACTIVE"]
            chosen = (active or locations or [{}])[0]
            mark_connected(
                db,
                "square",
                access,
                refresh_token=refresh,
                location_id=chosen.get("id") or settings.square_location_id,
                merchant_id=payload.get("merchant_id") or chosen.get("merchant_id") or "",
                token_type="oauth",
            )
        _flash(request, ok="Square is connected. Sales will land in the cellar.")
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "square", str(exc))
        _flash(request, err=f"Square connect failed: {exc}")
    return _redirect_connect()


@router.post("/connect/square/token")
def save_square_token(
    request: Request,
    access_token: str = Form(""),
    db: Session = Depends(get_db),
):
    token = strip_auth_prefix(access_token)
    if not token:
        _flash(request, err="Paste the Square access token first.")
        return _redirect_connect()
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            loc = client.get(
                f"{square_host()}/v2/locations",
                headers={"Authorization": f"Bearer {token}", "Square-Version": "2025-01-23"},
            )
            loc.raise_for_status()
            locations = loc.json().get("locations") or []
            active = [item for item in locations if str(item.get("status", "")).upper() == "ACTIVE"]
            chosen = (active or locations or [{}])[0]
        mark_connected(
            db,
            "square",
            token,
            location_id=chosen.get("id") or settings.square_location_id,
            merchant_id=chosen.get("merchant_id") or "",
            token_type="personal",
        )
        _flash(request, ok="Square is connected.")
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "square", str(exc))
        _flash(request, err="That Square token did not work. Copy the Production access token and try again.")
    return _redirect_connect()


@router.post("/connect/mealie")
def connect_mealie(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    if not username or not password:
        _flash(request, err="Enter the same Mealie email and password you already use.")
        return _redirect_connect()
    base = settings.mealie_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{base}/api/auth/token",
                data={"username": username.strip(), "password": password, "grant_type": "password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 400:
                response = client.post(
                    f"{base}/api/auth/token",
                    json={"username": username.strip(), "password": password},
                )
            response.raise_for_status()
            token = response.json().get("access_token") or ""
            if not token:
                raise RuntimeError("Mealie did not return a token")
            check = client.get(f"{base}/api/recipes", headers={"Authorization": f"Bearer {token}"}, params={"perPage": 1})
            check.raise_for_status()
        mark_connected(db, "mealie", token, login=username.strip())
        _flash(request, ok="Mealie is connected. Recipes will copy into costing.")
    except Exception:  # noqa: BLE001
        mark_error(db, "mealie", "login failed")
        _flash(request, err="Mealie login failed. Use the same email and password as on Mealie.")
    return _redirect_connect()


@router.post("/connect/paperless")
def connect_paperless(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    if not username or not password:
        _flash(request, err="Enter the same Paperless username and password you already use.")
        return _redirect_connect()
    base = settings.paperless_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base}/api/token/", json={"username": username.strip(), "password": password})
            response.raise_for_status()
            token = response.json().get("token") or ""
            if not token:
                raise RuntimeError("Paperless did not return a token")
            check = client.get(
                f"{base}/api/documents/",
                headers={"Authorization": f"Token {token}"},
                params={"page_size": 1},
            )
            check.raise_for_status()
        mark_connected(db, "paperless", token, login=username.strip())
        _flash(request, ok="Paperless is connected. Invoices will copy into costing.")
    except Exception:  # noqa: BLE001
        mark_error(db, "paperless", "login failed")
        _flash(request, err="Paperless login failed. Use the same username and password as on Paperless.")
    return _redirect_connect()


@router.post("/connect/vendor/{slug}")
def connect_vendor(
    slug: str,
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    vendor = vendor_by_slug(slug)
    if vendor is None:
        return _redirect_connect()
    login = username.strip()
    if not login or not password:
        _flash(request, err=f"Enter the same email and password you use to log in to {vendor['label']}.")
        return _redirect_connect()
    mark_connected(
        db,
        vendor["slug"],
        password,
        login=login,
        connector_name=vendor["label"],
    )
    _ensure_paperless_correspondent(db, vendor)
    _flash(request, ok=f"{vendor['label']} is connected. Paperless will file their invoices.")
    return _redirect_connect()


@router.post("/connect/{name}/disconnect")
def disconnect_service(name: str, request: Request, db: Session = Depends(get_db)):
    if name not in SYSTEM_NAMES and name not in VENDOR_SLUGS:
        return _redirect_connect()
    disconnect(db, name)
    vendor = vendor_by_slug(name)
    label = vendor["label"] if vendor else name.title()
    _flash(request, ok=f"{label} disconnected.")
    return _redirect_connect()


@router.post("/connect/sync")
def sync_now(request: Request, db: Session = Depends(get_db)):
    result = sync_all(db)
    parts = []
    errors = []
    for name, payload in result.items():
        if name == "ran_at" or not isinstance(payload, dict):
            continue
        status = payload.get("status")
        if status == "ok":
            parts.append(name.title())
        elif status == "error":
            errors.append(f"{name}: {payload.get('error')}")
    if parts and not errors:
        _flash(request, ok="Synced " + ", ".join(parts) + ".")
    elif parts:
        _flash(request, ok="Synced " + ", ".join(parts) + ".", err="; ".join(errors))
    elif errors:
        _flash(request, err="; ".join(errors))
    else:
        _flash(request, err="Nothing to sync yet. Connect Square, Mealie or Paperless first.")
    return _redirect_connect()


@router.get("/setup")
def setup_redirect():
    return _redirect_connect()
