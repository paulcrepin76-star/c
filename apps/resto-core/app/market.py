from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.catalog import record_catalog_quote
from app.config import settings
from app.geo import FALLBACK_MILES, FAR_MILES, HOME_MARKET, km_for_miles, miles_from_home, radius_band
from app.models import Connector, Product, PurchasePrice, Supplier
from app.purchasing import match_canonical_product
from app.units import family

USER_AGENT = "SurveyCafe-resto/0.1 (https://github.com/paulcrepin76-star/c)"
OPEN_PRICES = "https://prices.openfoodfacts.org/api/v1"
BLS = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

WATCH_QUERIES = {
    "BUTTER": ("unsalted butter", "butter"),
    "EGG": ("large eggs", "grade a eggs"),
    "MILK": ("whole milk",),
    "HEAVY-CREAM": ("heavy cream",),
    "SALMON": ("salmon",),
    "CHICKEN": ("chicken breast", "chicken"),
}

# Official US city-average retail prices. No API key required (low daily cap).
BLS_SERIES = {
    "BUTTER": {"id": "APU0000702212", "pack_qty": Decimal("1"), "pack_unit": "lb", "label": "Butter, grade AA, stick"},
    "EGG": {"id": "APU0000709112", "pack_qty": Decimal("1"), "pack_unit": "dozen", "label": "Eggs, grade A, large"},
    "MILK": {"id": "APU0000706111", "pack_qty": Decimal("1"), "pack_unit": "gal", "label": "Milk, fresh, whole"},
    "CHICKEN": {"id": "APU0000FF1101", "pack_qty": Decimal("1"), "pack_unit": "lb", "label": "Chicken, fresh, whole"},
}


def _headers() -> dict:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _get_json(url: str, params: dict | None = None) -> dict:
    with httpx.Client(headers=_headers(), timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _post_json(url: str, body: dict) -> dict:
    with httpx.Client(headers=_headers(), timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _ensure_supplier(db: Session, name: str, notes: str = "", city: str = "", miles: Decimal | int | float = 0) -> Supplier:
    label = name[:120]
    row = db.query(Supplier).filter(Supplier.name == label).first()
    if row is None:
        row = Supplier(
            name=label,
            category="food",
            default_invoice_type="food",
            notes=notes[:500] if notes else "",
            city=city[:80],
            miles=Decimal(str(miles or 0)),
        )
        db.add(row)
        db.flush()
        return row
    if city and not row.city:
        row.city = city[:80]
    if miles and not row.miles:
        row.miles = Decimal(str(miles))
    return row


def _ensure_connector(db: Session, name: str, status: str, notes: str) -> None:
    row = db.query(Connector).filter(Connector.name == name).first()
    if row is None:
        db.add(Connector(name=name, kind="catalog", status=status, notes=notes))
        db.flush()
        return
    row.status = status
    row.notes = notes
    from datetime import UTC, datetime

    row.last_run_at = datetime.now(UTC).replace(tzinfo=None)


def nearby_locations(max_miles: Decimal) -> list[dict]:
    payload = _get_json(
        f"{OPEN_PRICES}/locations/nearby",
        {"lat": settings.home_lat, "lon": settings.home_lon, "radius_km": round(km_for_miles(max_miles), 1), "size": 50},
    )
    found = []
    for item in payload.get("items") or []:
        lat = item.get("osm_lat")
        lon = item.get("osm_lon")
        if lat is None or lon is None:
            continue
        miles = miles_from_home(float(lat), float(lon))
        found.append({**item, "miles": miles, "band": radius_band(miles)})
    found.sort(key=lambda row: Decimal(str(row["miles"])))
    return found


def local_locations() -> tuple[list[dict], str]:
    near = nearby_locations(FAR_MILES)
    if near:
        return near, "local"
    wider = nearby_locations(FALLBACK_MILES)
    return wider, "florida"


def _pack_from_open_price(product: dict, price_row: dict) -> tuple[Decimal, str, Decimal] | None:
    amount = Decimal(str(price_row.get("price") or 0))
    if amount <= 0:
        return None
    price_per = str(price_row.get("price_per") or "UNIT").upper()
    if price_per == "KILOGRAM":
        return Decimal("1"), "kg", amount
    qty = product.get("product_quantity")
    unit = str(product.get("product_quantity_unit") or "").strip().lower()
    if qty and unit and family(unit):
        return Decimal(str(qty)), unit, amount
    return None


def scan_open_prices(db: Session) -> dict:
    if not settings.open_prices_enabled:
        return {"status": "skipped", "quotes": 0, "locations": 0}
    try:
        locations, coverage = local_locations()
    except Exception as exc:  # noqa: BLE001
        _ensure_connector(db, "Open Prices", "error", str(exc)[:300])
        db.commit()
        return {"status": "error", "error": str(exc)[:200], "quotes": 0, "locations": 0}
    location_ids = [int(item["id"]) for item in locations if item.get("id")]
    miles_by_id = {int(item["id"]): item for item in locations if item.get("id")}
    scanned_on = date.today()
    quotes = 0
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    for sku, queries in WATCH_QUERIES.items():
        product = db.query(Product).filter(Product.sku == sku).first()
        if product is None:
            continue
        db.query(PurchasePrice).filter(
            PurchasePrice.product_id == product.id,
            PurchasePrice.source == "open_prices",
            PurchasePrice.purchased_on == scanned_on,
        ).delete(synchronize_session=False)
        db.flush()
        seen_codes: set[int] = set()
        for query in queries:
            try:
                found = _get_json(
                    f"{OPEN_PRICES}/products",
                    {"product_name__like": query, "price_count__gte": 1, "size": 20},
                )
            except Exception:  # noqa: BLE001
                continue
            for item in found.get("items") or []:
                pid = int(item.get("id") or 0)
                if not pid or pid in seen_codes:
                    continue
                matched, _score = match_canonical_product(db, str(item.get("product_name") or query))
                if matched is None or matched.id != product.id:
                    continue
                seen_codes.add(pid)
                params = {
                    "product_id": pid,
                    "currency": "USD",
                    "date__gte": cutoff,
                    "size": 30,
                    "order_by": "-date",
                }
                if location_ids:
                    params["location_id__in"] = ",".join(str(loc) for loc in location_ids[:40])
                try:
                    priced = _get_json(f"{OPEN_PRICES}/prices", params)
                except Exception:  # noqa: BLE001
                    continue
                rows = priced.get("items") or []
                if not rows and location_ids:
                    params.pop("location_id__in", None)
                    try:
                        priced = _get_json(f"{OPEN_PRICES}/prices", params)
                        rows = priced.get("items") or []
                    except Exception:  # noqa: BLE001
                        rows = []
                for price_row in rows:
                    loc = price_row.get("location") or {}
                    loc_id = int(price_row.get("location_id") or loc.get("id") or 0)
                    info = miles_by_id.get(loc_id) or {}
                    lat, lon = loc.get("osm_lat"), loc.get("osm_lon")
                    miles = info.get("miles")
                    if miles is None and lat is not None and lon is not None:
                        miles = miles_from_home(float(lat), float(lon))
                    miles = Decimal(str(miles or 0))
                    pack = _pack_from_open_price(item, price_row)
                    if pack is None:
                        continue
                    pack_qty, pack_unit, pack_price = pack
                    city = str(loc.get("osm_address_city") or info.get("osm_address_city") or "").strip()
                    store = str(loc.get("osm_name") or info.get("osm_name") or "Open Prices").strip()
                    label = f"{store} · {city}" if city else store
                    supplier = _ensure_supplier(db, label, notes="Open Prices crowdsourced", city=city, miles=miles)
                    recorded = record_catalog_quote(
                        db,
                        product,
                        supplier,
                        {
                            "sku": str(item.get("code") or "")[:80],
                            "description": str(item.get("product_name") or store)[:240],
                            "pack_qty": pack_qty,
                            "pack_unit": pack_unit,
                            "pack_price": pack_price,
                            "url": f"https://prices.openfoodfacts.org/locations/{loc_id}" if loc_id else OPEN_PRICES,
                            "miles": miles,
                            "location_label": f"{label} · {HOME_MARKET}"[:160],
                            "is_discounted": bool(price_row.get("price_is_discounted")),
                        },
                        scanned_on,
                        source="open_prices",
                    )
                    if recorded:
                        quotes += 1
    note = (
        f"{len(locations)} store(s) in the {coverage} radius around {HOME_MARKET}. "
        "Crowdsourced — a missing Publix or Sam's just means nobody uploaded a receipt yet."
    )
    _ensure_connector(db, "Open Prices", "ready" if locations else "manual", note)
    db.commit()
    return {
        "status": "ok",
        "quotes": quotes,
        "locations": len(locations),
        "coverage": coverage,
        "market": HOME_MARKET,
    }


def scan_bls(db: Session) -> dict:
    if not settings.bls_enabled:
        return {"status": "skipped", "quotes": 0}
    series_ids = [spec["id"] for spec in BLS_SERIES.values()]
    try:
        payload = _post_json(BLS, {"seriesid": series_ids})
    except Exception as exc:  # noqa: BLE001
        _ensure_connector(db, "US retail average (BLS)", "error", str(exc)[:300])
        db.commit()
        return {"status": "error", "error": str(exc)[:200], "quotes": 0}
    if payload.get("status") != "REQUEST_SUCCEEDED":
        message = ",".join(payload.get("message") or [])[:300] or "BLS request failed"
        _ensure_connector(db, "US retail average (BLS)", "error", message)
        db.commit()
        return {"status": "error", "error": message, "quotes": 0}
    by_id = {}
    for series in (payload.get("Results") or {}).get("series") or []:
        points = series.get("data") or []
        if not points:
            continue
        latest = points[0]
        by_id[series.get("seriesID")] = latest
    supplier = _ensure_supplier(
        db,
        "US retail average (BLS)",
        notes="Official US city-average retail. Benchmark only — not a store you can buy from.",
        city="United States",
        miles=0,
    )
    scanned_on = date.today()
    quotes = 0
    for sku, spec in BLS_SERIES.items():
        product = db.query(Product).filter(Product.sku == sku).first()
        point = by_id.get(spec["id"])
        if product is None or point is None:
            continue
        try:
            price = Decimal(str(point.get("value")))
        except Exception:  # noqa: BLE001
            continue
        if price <= 0:
            continue
        period = f"{point.get('periodName', '')} {point.get('year', '')}".strip()
        recorded = record_catalog_quote(
            db,
            product,
            supplier,
            {
                "sku": spec["id"],
                "description": f"{spec['label']} · {period}",
                "pack_qty": spec["pack_qty"],
                "pack_unit": spec["pack_unit"],
                "pack_price": price,
                "url": "https://www.bls.gov/data/",
                "miles": 0,
                "location_label": f"US city average · {period}",
                "is_discounted": False,
            },
            scanned_on,
            source="bls",
        )
        if recorded:
            quotes += 1
    _ensure_connector(
        db,
        "US retail average (BLS)",
        "ready",
        "US city-average retail from the Bureau of Labor Statistics. USDA MyMarketNews wholesale needs USDA_MMN_API_KEY.",
    )
    db.commit()
    return {"status": "ok", "quotes": quotes}


def scan_usda(db: Session) -> dict:
    if not settings.usda_mmn_api_key:
        _ensure_connector(
            db,
            "USDA MyMarketNews",
            "not_connected",
            "Wholesale dairy/meat reports. Add USDA_MMN_API_KEY to .env. Until then the BLS retail average is the government benchmark.",
        )
        db.commit()
        return {"status": "skipped", "reason": "needs USDA_MMN_API_KEY"}
    return {"status": "skipped", "reason": "key present but report map not loaded yet"}


def scan_external_prices(db: Session) -> dict:
    open_prices = scan_open_prices(db)
    bls = scan_bls(db)
    usda = scan_usda(db)
    stored = (
        db.query(PurchasePrice)
        .filter(
            PurchasePrice.source.in_(("open_prices", "bls", "usda")),
            PurchasePrice.purchased_on == date.today(),
        )
        .count()
    )
    return {
        "status": "ok",
        "quotes": stored,
        "open_prices": open_prices,
        "bls": bls,
        "usda": usda,
        "market": HOME_MARKET,
    }
