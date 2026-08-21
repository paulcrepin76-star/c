from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Connection, Connector


def get_connection(db: Session, name: str) -> Connection:
    row = db.query(Connection).filter(Connection.name == name).first()
    if row is None:
        row = Connection(name=name, status="not_connected")
        db.add(row)
        db.flush()
    return row


def extra_dict(row: Connection) -> dict:
    if not row.extra:
        return {}
    try:
        data = json.loads(row.extra)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def set_extra(row: Connection, **values) -> dict:
    data = extra_dict(row)
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    row.extra = json.dumps(data)
    return data


def strip_auth_prefix(token: str) -> str:
    value = (token or "").strip()
    lowered = value.lower()
    if lowered.startswith("bearer "):
        return value[7:].strip()
    if lowered.startswith("token "):
        return value[6:].strip()
    return value


def mark_connected(db: Session, name: str, access_token: str, refresh_token: str = "", **extra) -> Connection:
    row = get_connection(db, name)
    row.access_token = strip_auth_prefix(access_token)
    if refresh_token:
        row.refresh_token = refresh_token
    row.status = "connected"
    row.last_error = ""
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    if extra:
        set_extra(row, **extra)
    connector = db.query(Connector).filter(Connector.name.ilike(name)).first()
    if connector:
        connector.status = "ready"
        connector.last_error = ""
        connector.last_run_at = row.updated_at
    db.commit()
    db.refresh(row)
    return row


def mark_error(db: Session, name: str, message: str) -> Connection:
    row = get_connection(db, name)
    row.last_error = message[:500]
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    if row.status == "connected":
        row.status = "error"
    db.commit()
    return row


def disconnect(db: Session, name: str) -> Connection:
    row = get_connection(db, name)
    row.access_token = ""
    row.refresh_token = ""
    row.status = "not_connected"
    row.last_error = ""
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    kept = {key: value for key, value in extra_dict(row).items() if key in {"application_id", "application_secret"}}
    row.extra = json.dumps(kept) if kept else ""
    connector = db.query(Connector).filter(Connector.name.ilike(name)).first()
    if connector:
        connector.status = "not_connected"
    db.commit()
    return row


def access_token_for(db: Session, name: str) -> str:
    row = get_connection(db, name)
    if row.access_token:
        return strip_auth_prefix(row.access_token)
    fallback = {
        "square": settings.square_access_token,
        "mealie": settings.mealie_api_token,
        "paperless": settings.paperless_api_token,
    }
    return strip_auth_prefix(fallback.get(name, ""))


def square_host() -> str:
    if settings.square_environment == "sandbox":
        return "https://connect.squareupsandbox.com"
    return "https://connect.squareup.com"


def square_app_creds(db: Session) -> tuple[str, str]:
    extra = extra_dict(get_connection(db, "square"))
    app_id = str(extra.get("application_id") or settings.square_application_id or "").strip()
    app_secret = str(extra.get("application_secret") or settings.square_application_secret or "").strip()
    return app_id, app_secret
