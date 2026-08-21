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


def set_user_password(password: str, with_salt: bool) -> None:
    salt = str(uuid.uuid4()) if with_salt else "default"
    material = (salt + password) if with_salt else password
    hashed = bcrypt.hashpw(material.encode(), bcrypt.gensalt(10, prefix=b"2a")).decode()
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
        if row:
            cur.execute(
                "UPDATE core_user SET password = %s, password_salt = %s, is_superuser = TRUE, is_active = TRUE WHERE id = %s",
                (hashed, salt, row[0]),
            )
            user_id = row[0]
        else:
            cur.execute(
                """
                INSERT INTO core_user (
                    email, first_name, last_name, password, password_salt,
                    date_joined, is_superuser, is_active, is_qbnewb, is_datasetnewb, type
                ) VALUES (
                    %s, 'Cellar', 'Bot', %s, %s, NOW(), TRUE, TRUE, FALSE, FALSE, 'personal'
                ) RETURNING id
                """,
                (BOT_EMAIL, hashed, salt),
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
    conn.close()


def login(password: str) -> str:
    last_error = ""
    for with_salt in (True, False):
        set_user_password(password, with_salt=with_salt)
        response = httpx.post(
            f"{MB_URL}/api/session",
            json={"username": BOT_EMAIL, "password": password},
            timeout=30.0,
        )
        if response.status_code < 400:
            return response.json()["id"]
        last_error = f"{response.status_code} {response.text[:200]}"
    raise SystemExit(f"Metabase login failed: {last_error}")


def bot_password() -> str:
    BOT_ENV.parent.mkdir(parents=True, exist_ok=True)
    if BOT_ENV.exists():
        for line in BOT_ENV.read_text().splitlines():
            if line.startswith("MB_BOT_PASSWORD="):
                return line.split("=", 1)[1].strip()
    password = uuid.uuid4().hex + "Aa1!"
    BOT_ENV.write_text(f"MB_BOT_EMAIL={BOT_EMAIL}\nMB_BOT_PASSWORD={password}\n")
    os.chmod(BOT_ENV, 0o600)
    return password


def api(session: str, method: str, path: str, payload=None):
    kwargs = {
        "headers": {"X-Metabase-Session": session, "Content-Type": "application/json"},
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


def viz_settings(display: str) -> dict:
    if display == "scalar":
        return {"scalar.field": None}
    if display == "line":
        return {"graph.dimensions": ["day"], "graph.metrics": ["sales"]}
    if display == "bar":
        return {}
    return {}


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
        "visualization_settings": viz_settings(question["display"]),
    }
    for row in rows:
        if row.get("name") == question["name"] and row.get("collection_id") == collection_id:
            api(session, "PUT", f"/api/card/{row['id']}", payload)
            return int(row["id"])
    created = api(session, "POST", "/api/card", payload)
    return int(created["id"])


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


def main() -> int:
    wait_health()
    questions = parse_questions(QUESTIONS)
    if not questions:
        log("No questions found")
        return 1
    password = bot_password()
    session = login(password)
    db_id = ensure_database(session)
    collection_id = ensure_collection(session)
    card_ids = []
    for question in questions:
        card_id = ensure_card(session, db_id, collection_id, question)
        card_ids.append((question["name"], card_id, question["display"]))
        log(f"card {question['name']}")
    dash_id = ensure_dashboard(session, collection_id, card_ids)
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
