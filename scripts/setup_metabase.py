#!/usr/bin/env python3
"""Idempotent Metabase bootstrap for Survey Cafe. Does not print secrets."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import bcrypt
import httpx
import psycopg2
import secrets
import base64

MB_URL = os.environ.get("MB_URL", "http://metabase:3000").rstrip("/")
BOT_EMAIL = os.environ.get("MB_BOT_EMAIL", "cellar-bot@surveycafe.local")
BOT_ENV = Path(os.environ.get("MB_BOT_ENV", "/work/metabase/bot.env"))
QUESTIONS = Path(os.environ.get("MB_QUESTIONS", "/work/metabase/questions.sql"))
PG = {
    "host": os.environ.get("MB_PG_HOST", "postgres"),
    "port": int(os.environ.get("MB_PG_PORT", "5432")),
    "dbname": os.environ.get("POSTGRES_DB", "resto"),
    "user": os.environ.get("POSTGRES_USER", "resto"),
    "password": os.environ.get("POSTGRES_PASSWORD", ""),
}
METABASE_DB = os.environ.get("MB_DB_NAME", "metabase")
RESTO_DB_NAME = "Survey Cafe cellar"
COLLECTION = "Survey Cafe"
DASHBOARD = "Survey Cafe"


def log(msg: str) -> None:
    print(msg, flush=True)


def wait_health() -> None:
    for _ in range(60):
        try:
            response = httpx.get(f"{MB_URL}/api/health", timeout=5.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("Metabase did not become healthy")


def parse_questions(path: Path) -> list[dict]:
    text = path.read_text()
    chunks = re.split(r"\n(?=-- name:)", text)
    rows = []
    for chunk in chunks:
        match = re.search(r"^-- name:\s*(.+)$", chunk, re.M)
        if not match:
            continue
        display_match = re.search(r"^-- display:\s*(.+)$", chunk, re.M)
        sql = re.sub(r"^--.*$", "", chunk, flags=re.M).strip().rstrip(";")
        if not sql:
            continue
        rows.append(
            {
                "name": match.group(1).strip(),
                "display": (display_match.group(1).strip() if display_match else "table"),
                "sql": sql,
            }
        )
    return rows


def bcrypt2a(text: str) -> str:
    return bcrypt.hashpw(text.encode(), bcrypt.gensalt(10, prefix=b"2a")).decode()


def ensure_api_key() -> str:
    BOT_ENV.parent.mkdir(parents=True, exist_ok=True)
    raw = ""
    if BOT_ENV.exists():
        for line in BOT_ENV.read_text().splitlines():
            if line.startswith("MB_API_KEY=") and line.split("=", 1)[1].startswith("mb_"):
                raw = line.split("=", 1)[1].strip()
    if not raw:
        raw = "mb_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        BOT_ENV.write_text(f"MB_API_KEY={raw}\n")
        os.chmod(BOT_ENV, 0o600)

    hashed = bcrypt2a(raw)
    prefix = raw[:7]
    conn = psycopg2.connect(
        host=PG["host"],
        port=PG["port"],
        dbname=METABASE_DB,
        user=PG["user"],
        password=PG["password"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM core_user WHERE email = %s", (BOT_EMAIL,))
        row = cur.fetchone()
        dummy = str(uuid.uuid4())
        dummy_hash = bcrypt2a(dummy)
        if row:
            user_id = row[0]
            cur.execute(
                "UPDATE core_user SET type = 'api-key', is_superuser = TRUE, is_active = TRUE, password = %s, password_salt = %s WHERE id = %s",
                (dummy_hash, str(uuid.uuid4()), user_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO core_user (
                    email, first_name, last_name, password, password_salt,
                    date_joined, is_superuser, is_active, is_qbnewb, is_datasetnewb, type
                ) VALUES (
                    %s, 'Survey Cafe', 'API', %s, %s, NOW(), TRUE, TRUE, FALSE, FALSE, 'api-key'
                ) RETURNING id
                """,
                (BOT_EMAIL, dummy_hash, str(uuid.uuid4())),
            )
            user_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO permissions_group_membership (user_id, group_id, is_group_manager)
            SELECT %s, id, FALSE FROM permissions_group WHERE name IN ('All Users', 'Administrators')
            ON CONFLICT (user_id, group_id) DO NOTHING
            """,
            (user_id,),
        )
        cur.execute("SELECT id FROM api_key WHERE name = %s", ("Survey Cafe cellar",))
        key_row = cur.fetchone()
        if key_row:
            cur.execute(
                "UPDATE api_key SET key = %s, key_prefix = %s, user_id = %s, updated_at = NOW() WHERE id = %s",
                (hashed, prefix, user_id, key_row[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO api_key (user_id, key, key_prefix, creator_id, name, updated_by_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (user_id, hashed, prefix, user_id, "Survey Cafe cellar", user_id),
            )
    conn.close()
    return raw


def api(api_key: str, method: str, path: str, payload=None):
    kwargs = {
        "headers": {"X-API-Key": api_key, "Content-Type": "application/json"},
        "timeout": 60.0,
    }
    if payload is not None:
        kwargs["json"] = payload
    response = httpx.request(method, f"{MB_URL}{path}", **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text[:400]}")
    if response.content:
        return response.json()
    return {}


def ensure_database(session: str) -> int:
    existing = api(session, "GET", "/api/database")
    rows = existing.get("data") if isinstance(existing, dict) else existing
    for row in rows or []:
        if row.get("name") == RESTO_DB_NAME:
            return int(row["id"])
    created = api(
        session,
        "POST",
        "/api/database",
        {
            "engine": "postgres",
            "name": RESTO_DB_NAME,
            "details": {
                "host": PG["host"],
                "port": PG["port"],
                "dbname": PG["dbname"],
                "user": PG["user"],
                "password": PG["password"],
                "ssl": False,
            },
            "is_full_sync": True,
            "is_on_demand": False,
            "auto_run_queries": True,
        },
    )
    db_id = int(created["id"])
    try:
        api(session, "POST", f"/api/database/{db_id}/sync_schema")
    except Exception as exc:  # noqa: BLE001
        log(f"schema sync skipped: {exc}")
    return db_id


def ensure_collection(session: str) -> int:
    tree = api(session, "GET", "/api/collection")
    for row in tree if isinstance(tree, list) else tree.get("data") or []:
        if row.get("name") == COLLECTION:
            return int(row["id"])
    created = api(session, "POST", "/api/collection", {"name": COLLECTION, "color": "#509EE3"})
    return int(created["id"])


def viz_for(display: str, cols: list[dict] | None = None) -> dict:
    names = [str(col.get("name") or "") for col in cols or []]
    numbers = [
        str(col.get("name"))
        for col in cols or []
        if str(col.get("base_type") or "").endswith(("Integer", "Decimal", "Float", "BigInteger", "Number"))
        or "type/Integer" in str(col.get("base_type"))
        or "type/Decimal" in str(col.get("base_type"))
        or "type/Float" in str(col.get("base_type"))
    ]
    dates = [
        str(col.get("name"))
        for col in cols or []
        if "Date" in str(col.get("base_type") or "") or "Time" in str(col.get("base_type") or "")
    ]
    texts = [name for name in names if name not in numbers and name not in dates]
    if display == "scalar":
        field = numbers[0] if numbers else (names[0] if names else None)
        return {"scalar.field": field} if field else {}
    if display == "line":
        dim = dates[0] if dates else (texts[0] if texts else None)
        metric = numbers[0] if numbers else None
        settings = {}
        if dim:
            settings["graph.dimensions"] = [dim]
        if metric:
            settings["graph.metrics"] = [metric]
        return settings
    if display == "bar":
        dim = texts[0] if texts else (dates[0] if dates else None)
        metric = numbers[0] if numbers else None
        settings = {}
        if dim:
            settings["graph.dimensions"] = [dim]
        if metric:
            settings["graph.metrics"] = [metric]
        return settings
    return {}


def finish_card(session: str, card_id: int, display: str) -> None:
    result = api(session, "POST", f"/api/card/{card_id}/query")
    cols = ((result.get("data") or {}).get("cols")) or []
    card = api(session, "GET", f"/api/card/{card_id}")
    payload = {
        "name": card.get("name"),
        "display": display,
        "dataset_query": card.get("dataset_query"),
        "visualization_settings": viz_for(display, cols),
        "collection_id": card.get("collection_id"),
    }
    if cols:
        payload["result_metadata"] = [
            {
                "name": col.get("name"),
                "display_name": col.get("display_name") or col.get("name"),
                "base_type": col.get("base_type"),
                "effective_type": col.get("effective_type") or col.get("base_type"),
                "semantic_type": col.get("semantic_type"),
                "field_ref": col.get("field_ref"),
            }
            for col in cols
        ]
    api(session, "PUT", f"/api/card/{card_id}", payload)


def ensure_card(session: str, db_id: int, collection_id: int, question: dict) -> int:
    cards = api(session, "GET", "/api/card")
    rows = cards if isinstance(cards, list) else cards.get("data") or []
    payload = {
        "name": question["name"],
        "display": question["display"],
        "collection_id": collection_id,
        "dataset_query": {
            "type": "native",
            "native": {"query": question["sql"]},
            "database": db_id,
        },
        "visualization_settings": {},
    }
    card_id = None
    for row in rows:
        if row.get("name") == question["name"] and row.get("collection_id") == collection_id:
            api(session, "PUT", f"/api/card/{row['id']}", payload)
            card_id = int(row["id"])
            break
    if card_id is None:
        created = api(session, "POST", "/api/card", payload)
        card_id = int(created["id"])
    finish_card(session, card_id, question["display"])
    return card_id


def ensure_dashboard(session: str, collection_id: int, card_ids: list[tuple[str, int, str]]) -> int:
    boards = api(session, "GET", "/api/dashboard")
    rows = boards if isinstance(boards, list) else boards.get("data") or []
    dash_id = None
    for row in rows:
        if row.get("name") == DASHBOARD:
            dash_id = int(row["id"])
            break
    if dash_id is None:
        created = api(session, "POST", "/api/dashboard", {"name": DASHBOARD, "collection_id": collection_id})
        dash_id = int(created["id"])

    layout = []
    row_i = 0
    scalars = [(name, cid) for name, cid, display in card_ids if display == "scalar"]
    others = [(name, cid, display) for name, cid, display in card_ids if display != "scalar"]
    dash_id_neg = -1
    col = 0
    for name, cid in scalars:
        layout.append(
            {
                "id": dash_id_neg,
                "card_id": cid,
                "row": row_i,
                "col": col,
                "size_x": 6,
                "size_y": 4,
                "parameter_mappings": [],
                "visualization_settings": {},
            }
        )
        dash_id_neg -= 1
        col += 6
        if col >= 24:
            col = 0
            row_i += 4
    if scalars:
        row_i += 4 if col else 0
        if col:
            row_i += 4
            col = 0
    for name, cid, display in others:
        width = 24 if display in {"line", "table"} and "by day" in name.lower() else 12
        height = 8 if display != "table" else 9
        if name in {"Latest purchase prices", "Top selling items YTD"}:
            width, height = 24, 10
        if col + width > 24:
            col = 0
            row_i += height
        layout.append(
            {
                "id": dash_id_neg,
                "card_id": cid,
                "row": row_i,
                "col": col,
                "size_x": width,
                "size_y": height,
                "parameter_mappings": [],
                "visualization_settings": {},
            }
        )
        dash_id_neg -= 1
        col += width
        if col >= 24:
            col = 0
            row_i += height

    current = api(session, "GET", f"/api/dashboard/{dash_id}")
    api(
        session,
        "PUT",
        f"/api/dashboard/{dash_id}",
        {
            "name": DASHBOARD,
            "collection_id": collection_id,
            "dashcards": layout,
            "parameters": current.get("parameters") or [],
            "width": current.get("width") or "full",
        },
    )
    return dash_id


def set_homepage(session: str, dash_id: int) -> None:
    try:
        api(session, "PUT", "/api/setting/custom-homepage", True)
        api(session, "PUT", "/api/setting/custom-homepage-dashboard", dash_id)
        log(f"homepage set to dashboard {dash_id}")
    except Exception as exc:  # noqa: BLE001
        log(f"homepage skipped: {exc}")


def main() -> int:
    wait_health()
    questions = parse_questions(QUESTIONS)
    if not questions:
        log("No questions found")
        return 1
    api_key = ensure_api_key()
    db_id = ensure_database(api_key)
    collection_id = ensure_collection(api_key)
    card_ids = []
    for question in questions:
        card_id = ensure_card(api_key, db_id, collection_id, question)
        card_ids.append((question["name"], card_id, question["display"]))
        log(f"card {question['name']}")
    dash_id = ensure_dashboard(api_key, collection_id, card_ids)
    set_homepage(api_key, dash_id)
    log(f"dashboard {DASHBOARD} id={dash_id} cards={len(card_ids)}")
    log(f"open {os.environ.get('METABASE_PUBLIC_URL', 'http://100.116.48.120:3001')}")
    log(f"log in as the Metabase user you already created (paulcrepin76@gmail.com)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(str(exc)[:500])
        sys.exit(1)
