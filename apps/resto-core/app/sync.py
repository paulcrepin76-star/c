from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import access_token_for, extra_dict, get_connection, mark_error, set_extra, square_host
from app.ingest import clean_food_name, ingest_paperless_doc, ingest_recipes, ingest_sales
from app.matching import match_sellables
from app.models import Sale
from app.purchasing import backfill_purchase_prices

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def infer_costing_group(name: str) -> str:
    lower = name.lower()
    if any(word in lower for word in ("wine", "sauvignon", "pinot", "champagne", "cabernet", "chardonnay", "merlot", "prosecco", "rose", "blanc", "noir", "bordeaux", "rioja")):
        return "wine"
    if any(word in lower for word in ("beer", "ipa", "lager", "stout", "cider")):
        return "beer"
    if any(word in lower for word in ("coffee", "espresso", "juice", "soda", "cocktail", "sangria", "spritz")):
        return "beverage"
    return "food"


def infer_invoice_type(title: str, doc_type: str = "") -> str:
    blob = f"{title} {doc_type}".lower()
    if any(word in blob for word in ("fpl", "comcast", "waste", "water", "utility", "electric", "bsu")):
        return "utility"
    if any(word in blob for word in ("wine", "vin", "champagne")):
        return "wine"
    if any(word in blob for word in ("costco", "gordon", "gfs", "sam's", "sams", "chef", "depot")):
        return "food"
    return "food"


def _square_lookback_days(db: Session, days: int | None) -> int:
    if days is not None:
        return days
    real = (
        db.query(Sale)
        .filter(Sale.square_order_id != "", ~Sale.square_order_id.like("demo-%"))
        .count()
    )
    return 365 if real == 0 else 7


def sync_square(db: Session, days: int | None = None) -> dict:
    token = access_token_for(db, "square")
    if not token:
        return {"status": "skipped", "reason": "not connected"}
    extra = extra_dict(get_connection(db, "square"))
    location_id = str(extra.get("location_id") or settings.square_location_id or "")
    host = square_host()
    lookback = _square_lookback_days(db, days)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Square-Version": "2025-01-23",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if not location_id:
                loc = client.get(f"{host}/v2/locations", headers=headers)
                loc.raise_for_status()
                locations = loc.json().get("locations") or []
                active = [item for item in locations if str(item.get("status", "")).upper() == "ACTIVE"]
                chosen = (active or locations or [None])[0]
                if not chosen:
                    raise RuntimeError("Square has no locations on this account")
                location_id = chosen["id"]
                row = get_connection(db, "square")
                set_extra(row, location_id=location_id)
                db.commit()
            end = datetime.now(UTC)
            start = end - timedelta(days=lookback)
            sales: list[dict] = []
            cursor = None
            while True:
                body = {
                    "location_ids": [location_id],
                    "query": {
                        "filter": {
                            "date_time_filter": {
                                "closed_at": {
                                    "start_at": start.isoformat().replace("+00:00", "Z"),
                                    "end_at": end.isoformat().replace("+00:00", "Z"),
                                }
                            },
                            "state_filter": {"states": ["COMPLETED"]},
                        }
                    },
                    "limit": 100,
                }
                if cursor:
                    body["cursor"] = cursor
                response = client.post(f"{host}/v2/orders/search", headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
                for order in payload.get("orders") or []:
                    for line in order.get("line_items") or []:
                        name = str(line.get("name") or "")
                        sales.append(
                            {
                                "sold_at": order.get("closed_at") or order.get("created_at"),
                                "name": name,
                                "qty": line.get("quantity") or 1,
                                "unit_price": (line.get("base_price_money") or {}).get("amount", 0) / 100,
                                "revenue": (line.get("total_money") or {}).get("amount", 0) / 100,
                                "square_order_id": order.get("id") or "",
                                "square_line_id": line.get("uid") or name,
                                "square_item_id": line.get("catalog_object_id") or "",
                                "costing_group": infer_costing_group(name),
                            }
                        )
                cursor = payload.get("cursor")
                if not cursor:
                    break
        result = ingest_sales(db, sales) if sales else {"created": 0, "skipped": 0}
        row = get_connection(db, "square")
        row.last_error = ""
        row.updated_at = _now()
        db.commit()
        return {"status": "ok", "days": lookback, "orders_lines": len(sales), **result}
    except Exception as exc:  # noqa: BLE001 — surface any API failure on the Connect page
        mark_error(db, "square", str(exc))
        return {"status": "error", "error": str(exc)}


def _mealie_recipe_payload(detail: dict) -> dict:
    name = str(detail.get("name") or detail.get("slug") or "").split("·")[0].strip()
    lines = []
    for ingredient in detail.get("recipeIngredient") or []:
        food = ""
        if isinstance(ingredient.get("food"), dict):
            food = str(ingredient["food"].get("name") or "")
        if not food:
            food = str(ingredient.get("display") or ingredient.get("note") or "")
        food = clean_food_name(food)
        if not food:
            continue
        unit_obj = ingredient.get("unit") or {}
        unit = ""
        if isinstance(unit_obj, dict):
            unit = str(unit_obj.get("abbreviation") or unit_obj.get("name") or "")
        lines.append({"name": food, "qty": ingredient.get("quantity") or 0, "unit": unit or "g"})
    yield_qty = detail.get("recipeYield") or detail.get("yield") or 1
    try:
        yield_qty = float(str(yield_qty).split()[0])
    except (TypeError, ValueError):
        yield_qty = 1
    return {
        "mealie_id": str(detail.get("id") or detail.get("slug") or ""),
        "name": name,
        "yield_qty": yield_qty,
        "yield_unit": "portion",
        "costing_group": infer_costing_group(name) if infer_costing_group(name) != "food" else (
            "beverage" if any(word in name.lower() for word in ("sangria", "cocktail", "drink")) else "food"
        ),
        "lines": lines,
    }


def sync_mealie(db: Session) -> dict:
    token = access_token_for(db, "mealie")
    if not token:
        return {"status": "skipped", "reason": "not connected"}
    base = settings.mealie_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        recipes: list[dict] = []
        with httpx.Client(timeout=TIMEOUT) as client:
            listing = client.get(f"{base}/api/recipes", headers=headers, params={"perPage": 200, "page": 1})
            listing.raise_for_status()
            payload = listing.json()
            items = payload.get("items") if isinstance(payload, dict) else payload
            for item in items or []:
                slug = item.get("slug") or item.get("id")
                detail = item
                if slug and not item.get("recipeIngredient"):
                    detail_resp = client.get(f"{base}/api/recipes/{slug}", headers=headers)
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                recipes.append(_mealie_recipe_payload(detail))
        result = ingest_recipes(db, recipes) if recipes else {"created": 0, "updated": 0}
        row = get_connection(db, "mealie")
        row.last_error = ""
        row.updated_at = _now()
        db.commit()
        return {"status": "ok", "recipes": len(recipes), **result}
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "mealie", str(exc))
        return {"status": "error", "error": str(exc)}


def _paperless_maps(client: httpx.Client, base: str, headers: dict) -> tuple[dict, dict, dict]:
    correspondents: dict[str, str] = {}
    types: dict[str, str] = {}
    fields: dict[str, str] = {}
    for path, target, key in (
        ("/api/correspondents/", correspondents, "name"),
        ("/api/document_types/", types, "name"),
        ("/api/custom_fields/", fields, "name"),
    ):
        response = client.get(f"{base}{path}", headers=headers, params={"page_size": 200})
        if response.status_code != 200:
            continue
        for item in response.json().get("results") or []:
            target[str(item.get("id"))] = str(item.get(key) or "")
    return correspondents, types, fields


def _ingest_paperless_result(db: Session, doc: dict, correspondents: dict, types: dict, fields: dict) -> str:
    title = str(doc.get("title") or "")
    correspondent_id = doc.get("correspondent")
    correspondent = correspondents.get(str(correspondent_id), "") if correspondent_id else ""
    doc_type = types.get(str(doc.get("document_type") or ""), "")
    custom_values = {}
    for entry in doc.get("custom_fields") or []:
        field_id = str(entry.get("field") or "")
        custom_values[fields.get(field_id, field_id).lower()] = entry.get("value")
    invoice_number = custom_values.get("invoice number") or doc.get("archive_serial_number") or doc.get("id")
    total = custom_values.get("invoice total") or 0
    result = ingest_paperless_doc(
        db,
        {
            "id": doc.get("id"),
            "title": title,
            "correspondent": correspondent or None,
            "created": doc.get("created") or doc.get("added"),
            "invoice_number": str(invoice_number or ""),
            "total": total or 0,
            "invoice_type": infer_invoice_type(title, doc_type),
            "content": doc.get("content") or "",
            "lines": [],
        },
    )
    return str(result.get("status") or "")


def sync_paperless(db: Session, max_pages: int = 15) -> dict:
    token = access_token_for(db, "paperless")
    if not token:
        return {"status": "skipped", "reason": "not connected"}
    base = settings.paperless_base_url.rstrip("/")
    headers = {"Authorization": f"Token {token}"}
    pages = max(1, min(int(max_pages or 15), 15))
    try:
        created = 0
        updated = 0
        skipped = 0
        with httpx.Client(timeout=TIMEOUT) as client:
            correspondents, types, fields = _paperless_maps(client, base, headers)
            page = 1
            while page <= pages:
                response = client.get(
                    f"{base}/api/documents/",
                    headers=headers,
                    params={"page_size": 100, "ordering": "-added", "page": page},
                )
                response.raise_for_status()
                docs = response.json().get("results") or []
                if not docs:
                    break
                for doc in docs:
                    status = _ingest_paperless_result(db, doc, correspondents, types, fields)
                    if status == "created":
                        created += 1
                    elif status == "updated":
                        updated += 1
                    else:
                        skipped += 1
                if not response.json().get("next"):
                    break
                page += 1
        row = get_connection(db, "paperless")
        row.last_error = ""
        row.updated_at = _now()
        db.commit()
        return {"status": "ok", "created": created, "updated": updated, "skipped": skipped}
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "paperless", str(exc))
        return {"status": "error", "error": str(exc)}


def sync_all(db: Session) -> dict:
    square = sync_square(db)
    mealie = sync_mealie(db)
    paperless = sync_paperless(db)
    prices = {"status": "ok", "created": backfill_purchase_prices(db)}
    try:
        matched = match_sellables(db)
        matched["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        matched = {"status": "error", "error": str(exc), "recipes": 0, "wines": 0}
    return {
        "square": square,
        "mealie": mealie,
        "paperless": paperless,
        "purchasing": prices,
        "matched": matched,
        "ran_at": _now().isoformat(),
    }
