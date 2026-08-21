from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from app.equivalents import (
    connection_status,
    dedupe_products,
    resolve_product,
    search_queries,
    store_catalog_item,
    relevant_products,
    upsert_equivalent,
    walk_json_products,
)
from app.models import Connector, Product, PurchasePrice, Supplier
from app.purchasing import compare_unit_for
from app.units import comparable_cost, parse_pack, to_base

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

# Public pages only. No logins, no CAPTCHA bypass, no 2FA, no stealth.
# Nightly refresh only searches products the cafe already buys.
# Blocked club sites (Sam's, Costco) stay on receipts + the Chrome extension even if Connect says connected.
CATALOGS: list[dict] = [
    {
        "slug": "webstaurantstore",
        "label": "WebstaurantStore",
        "parser": "webstaurant",
        "kind": "public",
        "method": "public JSON/HTML",
        "blurb": "Restaurant cases with public prices. Best public match for cafe packs.",
        "search": "https://www.webstaurantstore.com/search/{slug}.html",
        "home": "https://www.webstaurantstore.com/",
    },
    {"slug": "sams-club", "label": "Sam's Club", "kind": "blocked", "method": "receipts + extension", "blurb": "Connected login files invoices. Catalog crawl is not allowed (PerimeterX / terms). Open Sam's in Chrome and send the page.", "home": "https://www.samsclub.com/"},
    {"slug": "costco", "label": "Costco", "kind": "blocked", "method": "receipts + extension", "blurb": "Costco prohibits automated catalog collection. Email receipts and the extension while you shop.", "home": "https://www.costco.com/"},
    {"slug": "walmart", "label": "Walmart", "kind": "blocked", "method": "receipts + extension", "blurb": "Search redirects to a bot wall from a server.", "home": "https://www.walmart.com/"},
    {"slug": "publix", "label": "Publix", "kind": "js", "method": "extension / Playwright", "blurb": "Weekly ad is public in a browser; HTML has no dollars until JavaScript runs.", "home": "https://www.publix.com/"},
    {"slug": "target", "label": "Target", "kind": "js", "method": "extension / Playwright", "blurb": "Prices load in the app shell, not in the first HTML.", "home": "https://www.target.com/"},
    {"slug": "aldi", "label": "Aldi", "kind": "js", "method": "extension / Playwright", "blurb": "Store finder first; no stable public search HTML.", "home": "https://www.aldi.us/"},
    {"slug": "heb", "label": "H-E-B", "kind": "blocked", "blurb": "Texas chain; search is not useful from a datacenter IP.", "home": "https://www.heb.com/"},
    {"slug": "bjs", "label": "BJ's Wholesale", "kind": "blocked", "blurb": "Club prices need a membership cookie.", "home": "https://www.bjs.com/"},
    {"slug": "restaurant-depot", "label": "Restaurant Depot", "kind": "login", "blurb": "Cash-and-carry. Prices after a member login, not on the public homepage.", "home": "https://www.restaurantdepot.com/"},
    {"slug": "chefs-warehouse", "label": "Chef's Warehouse", "kind": "login", "blurb": "Shop prices after account login. Itemized PDFs beat a scraper here.", "home": "https://www.chefswarehouse.com/"},
    {"slug": "gordon", "label": "Gordon Food Service", "kind": "login", "blurb": "order.gfs.com is an account portal.", "home": "https://order.gfs.com/"},
    {"slug": "sysco", "label": "Sysco", "kind": "login", "blurb": "Shop Sysco is behind a customer login.", "home": "https://shop.sysco.com/"},
    {"slug": "us-foods", "label": "US Foods", "kind": "login", "blurb": "Customer portal, not a public catalog.", "home": "https://www.usfoods.com/"},
    {"slug": "katom", "label": "KaTom", "kind": "blocked", "blurb": "Restaurant supply. Cloudflare 403 from this server.", "home": "https://www.katom.com/"},
    {"slug": "restaurantsupply", "label": "Restaurant Supply", "kind": "blocked", "blurb": "Same bot wall as KaTom.", "home": "https://www.restaurantsupply.com/"},
    {"slug": "foodservicedirect", "label": "FoodServiceDirect", "kind": "blocked", "blurb": "Cases online; anti-bot in front.", "home": "https://www.foodservicedirect.com/"},
    {"slug": "centralrestaurant", "label": "Central Restaurant Products", "kind": "js", "blurb": "Equipment-heavy; search is not a food catalog.", "home": "https://www.centralrestaurant.com/"},
    {"slug": "instacart", "label": "Instacart", "kind": "js", "blurb": "Store prices after choosing a shopper location in the browser.", "home": "https://www.instacart.com/"},
    {"slug": "amazon-fresh", "label": "Amazon Fresh", "kind": "blocked", "blurb": "Logged-in grocery prices. Skip.", "home": "https://www.amazon.com/alm/storefront?almBrandId=QW1hem9uIEZyZXNo"},
    {"slug": "performance-food", "label": "Performance Foodservice", "kind": "login", "blurb": "Broadline distributor portal.", "home": "https://www.pfgc.com/"},
    {"slug": "fulton-fish", "label": "Fulton Fish Market", "kind": "js", "blurb": "Public seafood shop; JS cart. Add a parser once HTML is stable.", "home": "https://fultonfishmarket.com/"},
    {"slug": "wild-alaskan", "label": "Wild Alaskan Company", "kind": "js", "blurb": "Subscription seafood. Public pack prices in the browser.", "home": "https://wildalaskancompany.com/"},
    {"slug": "sitka-salmon", "label": "Sitka Salmon Shares", "kind": "js", "blurb": "CSF seafood boxes, not cafe case packs.", "home": "https://sitkasalmonshares.com/"},
    {"slug": "costco-business", "label": "Costco Business Center", "kind": "login", "blurb": "Business Center list after sign-in. Photograph the receipt for paid history.", "home": "https://www.costcobusinesscentre.ca/"},
    {"slug": "walmart-business", "label": "Walmart Business", "kind": "login", "blurb": "Business account pricing.", "home": "https://www.walmart.com/business"},
    {"slug": "bjs-perks", "label": "BJ's Business", "kind": "login", "blurb": "Club business pricing after login.", "home": "https://www.bjs.com/"},
]

WATCH = {
    "BUTTER": ("unsalted butter",),
    "EGG": ("large eggs",),
    "MILK": ("whole milk",),
    "HEAVY-CREAM": ("heavy cream",),
    "SALMON": ("salmon fillet",),
    "CHICKEN": ("chicken breast",),
}


def _slug_query(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _price_amount(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("price", "salePrice", "amount"):
            if value.get(key):
                return Decimal(str(value[key]))
        return None
    try:
        amount = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    return amount if amount > 0 else None


_CASE_ALREADY = re.compile(r"\d+\s*/\s*(?:case|cs)\b", re.I)


def parse_webstaurant(html: str) -> list[dict]:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    if not scripts:
        return []
    raw = max(scripts, key=len).strip()
    if raw.startswith("<!--"):
        raw = raw[4:]
    if raw.endswith("-->"):
        raw = raw[:-3]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    found = []
    for item in payload.get("products") or []:
        description = str(item.get("description") or item.get("alt") or "")
        amount = _price_amount(item.get("price"))
        if not description or amount is None:
            continue
        pack_qty, pack_unit = parse_pack(description)
        units = item.get("unitsPerPackaging")
        if (
            units
            and pack_qty > 0
            and Decimal(str(units)) > 1
            and not _CASE_ALREADY.search(description)
        ):
            pack_qty = pack_qty * Decimal(str(units))
        if pack_qty <= 0 or not pack_unit:
            continue
        link = str(item.get("link") or "")
        if link.startswith("/"):
            link = "https://www.webstaurantstore.com" + link
        found.append(
            {
                "description": description[:240],
                "sku": str(item.get("itemNumber") or "")[:80],
                "brand": str(item.get("brand") or item.get("brandName") or "")[:120],
                "pack_price": amount,
                "regular_price": amount,
                "pack_qty": pack_qty,
                "pack_unit": pack_unit,
                "case_qty": Decimal(str(units or 0)) if units else Decimal("0"),
                "url": link[:400],
                "available": True,
            }
        )
    return found


def extract_html_json_products(html: str) -> list[dict]:
    found: list[dict] = []
    for raw in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I):
        text = raw.strip()
        if text.startswith("<!--"):
            text = text[4:]
        if text.endswith("-->"):
            text = text[:-3]
        text = text.strip()
        if len(text) < 20 or text[0] not in "{[":
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        found.extend(walk_json_products(payload))
    return dedupe_products(found)


PARSERS = {"webstaurant": parse_webstaurant}


def ensure_catalog_suppliers(db: Session) -> None:
    # Only fetchable catalogs become suppliers. Blocked grocery sites stay on the
    # lexicon; do not overwrite Chef's / Sam's / Costco email connectors.
    for source in CATALOGS:
        if not source.get("parser"):
            continue
        supplier = db.query(Supplier).filter(Supplier.name == source["label"]).first()
        if supplier is None:
            db.add(
                Supplier(
                    name=source["label"],
                    category="food",
                    default_invoice_type="food",
                    notes=source.get("blurb") or "",
                )
            )
        connector = db.query(Connector).filter(Connector.name == source["label"]).first()
        if connector is None:
            db.add(
                Connector(
                    name=source["label"],
                    kind="catalog",
                    status="ready",
                    notes=source.get("blurb") or "",
                )
            )
        else:
            connector.kind = "catalog"
            connector.notes = source.get("blurb") or connector.notes
    db.commit()


def _supplier_for(db: Session, label: str) -> Supplier | None:
    return db.query(Supplier).filter(Supplier.name == label).first()


def record_catalog_quote(
    db: Session,
    product: Product,
    supplier: Supplier,
    item: dict,
    scanned_on: date,
    source: str = "catalog",
) -> PurchasePrice | None:
    pack_qty = Decimal(str(item.get("pack_qty") or 0))
    pack_unit = str(item.get("pack_unit") or "")
    pack_price = Decimal(str(item.get("pack_price") or 0))
    if pack_qty <= 0 or pack_price <= 0:
        return None
    compare_unit = compare_unit_for(product)
    unit_compare = comparable_cost(pack_price, pack_qty, pack_unit, compare_unit)
    if unit_compare is None:
        return None
    qty_base = to_base(pack_qty, pack_unit, product.base_unit or compare_unit) or Decimal("0")
    unit_base = (pack_price / qty_base) if qty_base > 0 else Decimal("0")
    url = str(item.get("url") or "")[:400]
    existing_rows = (
        db.query(PurchasePrice)
        .filter(
            PurchasePrice.product_id == product.id,
            PurchasePrice.supplier_id == supplier.id,
            PurchasePrice.source == source,
            PurchasePrice.purchased_on == scanned_on,
        )
        .order_by(PurchasePrice.unit_cost_compare.asc(), PurchasePrice.id.asc())
        .all()
    )
    existing = existing_rows[0] if existing_rows else None
    for extra in existing_rows[1:]:
        db.delete(extra)
    if existing and Decimal(str(existing.unit_cost_compare)) <= unit_compare:
        db.flush()
        return existing
    row = existing or PurchasePrice(
        product_id=product.id,
        supplier_id=supplier.id,
        purchased_on=scanned_on,
        source=source,
    )
    row.sku = str(item.get("sku") or "")[:80]
    row.raw_description = str(item.get("description") or "")[:240]
    row.pack_qty = pack_qty
    row.pack_unit = pack_unit
    row.pack_price = pack_price
    row.qty_base = qty_base
    row.unit_cost_base = unit_base
    row.compare_qty = to_base(pack_qty, pack_unit, compare_unit) or Decimal("0")
    row.unit_cost_compare = unit_compare
    row.confidence = {
        "invoice": Decimal("1.00"),
        "extension": Decimal("0.95"),
        "auth_browser": Decimal("0.95"),
        "bls": Decimal("0.90"),
        "usda": Decimal("0.90"),
        "instacart": Decimal("0.90"),
        "catalog": Decimal("0.80"),
        "playwright": Decimal("0.80"),
        "open_prices": Decimal("0.70"),
    }.get(source, Decimal("0.80"))
    row.url = url
    row.miles = Decimal(str(item.get("miles") or supplier.miles or 0))
    row.location_label = str(item.get("location_label") or supplier.city or "")[:160]
    row.is_discounted = bool(item.get("is_discounted"))
    if existing is None:
        db.add(row)
    db.flush()
    upsert_equivalent(db, product, supplier, item, seen_on=scanned_on, source=source)
    store_catalog_item(db, supplier, item, scanned_on, product=product, source=source)
    return row


def _fetch(url: str) -> tuple[int, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        return response.status_code, response.text


def _query_hits(description: str, query: str) -> bool:
    text = description.lower()
    words = [word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2]
    return all(re.search(rf"(?<![a-z0-9]){re.escape(word)}", text) for word in words)


def _search_url(source: dict, query: str) -> str:
    template = source.get("search") or ""
    return template.replace("{slug}", _slug_query(query)).replace("{query}", quote_plus(query))


def scan_source(
    db: Session,
    source: dict,
    product: Product,
    query: str,
    scanned_on: date,
    mode: str = "refresh",
) -> dict:
    parser = PARSERS.get(source.get("parser") or "")
    if parser is None:
        return {"status": source.get("kind") or "skipped", "quotes": 0}
    url = _search_url(source, query)
    try:
        status, html = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:200], "quotes": 0}
    if status >= 400 or len(html) < 2000:
        return {"status": "blocked", "http": status, "quotes": 0}
    supplier = _supplier_for(db, source["label"])
    if supplier is None:
        return {"status": "error", "error": "missing supplier", "quotes": 0}
    items = parser(html)
    if not items:
        items = extract_html_json_products(html)
    recorded = 0
    unmatched = 0
    for item in items:
        if not _query_hits(item["description"], query):
            continue
        if item.get("url", "").startswith("/"):
            item["url"] = "https://www.webstaurantstore.com" + item["url"]
        matched = resolve_product(db, supplier, item["description"], str(item.get("sku") or ""))
        if matched is None or matched.id != product.id:
            if mode == "discovery" and matched is None:
                store_catalog_item(db, supplier, item, scanned_on, source="catalog", scan_mode=mode)
                unmatched += 1
            continue
        if record_catalog_quote(db, product, supplier, item, scanned_on):
            recorded += 1
    if recorded or unmatched:
        db.commit()
    return {"status": "ok", "http": status, "quotes": recorded, "unmatched": unmatched, "url": url}


def _source_skip(db: Session, source: dict) -> dict | None:
    kind = source.get("kind") or "listed"
    if source.get("parser"):
        return None
    connected = connection_status(db, source.get("slug") or "")
    if kind in ("blocked", "login"):
        return {
            "source": source["label"],
            "status": "receipts_or_extension",
            "quotes": 0,
            "connected": connected,
            "reason": source.get("blurb") or kind,
        }
    if kind == "js":
        return {
            "source": source["label"],
            "status": "needs_browser",
            "quotes": 0,
            "connected": connected,
            "reason": "Public JS prices: use the Chrome extension on the page, or Playwright later. No login crawl.",
        }
    return {
        "source": source["label"],
        "status": "listed",
        "quotes": 0,
        "connected": connected,
        "reason": source.get("blurb") or "",
    }


def scan_catalogs(db: Session, mode: str = "refresh") -> dict:
    ensure_catalog_suppliers(db)
    scanned_on = date.today()
    mode = "discovery" if mode == "discovery" else "refresh"
    watched = relevant_products(db, mode=mode)
    fetchable = [source for source in CATALOGS if source.get("parser")]
    results = []
    skipped = []
    quotes = 0
    unmatched = 0
    for source in CATALOGS:
        skip = _source_skip(db, source)
        if skip:
            skipped.append(skip)
            continue
        source_quotes = 0
        last_error = ""
        for product in watched:
            supplier = _supplier_for(db, source["label"])
            if supplier is not None:
                db.query(PurchasePrice).filter(
                    PurchasePrice.product_id == product.id,
                    PurchasePrice.supplier_id == supplier.id,
                    PurchasePrice.source == "catalog",
                    PurchasePrice.purchased_on == scanned_on,
                ).delete(synchronize_session=False)
                db.flush()
            queries = search_queries(db, product, mode=mode)
            extra = WATCH.get(product.sku) or ()
            for query in extra:
                if query.lower() not in queries:
                    queries.append(query)
            for query in queries:
                outcome = scan_source(db, source, product, query, scanned_on, mode=mode)
                source_quotes += int(outcome.get("quotes") or 0)
                unmatched += int(outcome.get("unmatched") or 0)
                if outcome.get("status") not in ("ok", "skipped") and not last_error:
                    last_error = str(outcome.get("error") or outcome.get("status") or "")
        quotes += source_quotes
        connector = db.query(Connector).filter(Connector.name == source["label"]).first()
        if connector:
            connector.status = "ready" if source_quotes or not last_error else "error"
            connector.last_error = last_error[:300]
            connector.last_run_at = datetime.now(UTC).replace(tzinfo=None)
            connector.notes = f"{mode} scan · {source_quotes} pack(s) for {len(watched)} relevant item(s)"
        results.append({"source": source["label"], "quotes": source_quotes, "error": last_error})
    db.commit()
    stored = (
        db.query(PurchasePrice)
        .filter(
            PurchasePrice.source == "catalog",
            PurchasePrice.purchased_on == scanned_on,
        )
        .count()
    )
    return {
        "status": "ok",
        "mode": mode,
        "relevant": len(watched),
        "quotes": stored,
        "matched": quotes,
        "unmatched": unmatched,
        "sources": results,
        "skipped": skipped,
        "lexicon": len(CATALOGS),
        "fetchable": len(fetchable),
        "scanned_on": scanned_on.isoformat(),
    }


def catalog_lexicon(db: Session | None = None) -> list[dict]:
    method_for = {
        "public": "public JSON/HTML",
        "js": "extension / Playwright",
        "login": "extension while logged in",
        "blocked": "receipts + extension",
    }
    rows = []
    for source in CATALOGS:
        kind = source.get("kind") or ("public" if source.get("parser") else "listed")
        connected = connection_status(db, source.get("slug") or "") if db is not None else ""
        rows.append(
            {
                "label": source["label"],
                "slug": source.get("slug") or "",
                "kind": kind,
                "method": source.get("method") or method_for.get(kind, kind),
                "blurb": source.get("blurb") or "",
                "home": source.get("home") or "",
                "fetchable": bool(source.get("parser")),
                "connected": connected,
            }
        )
    return rows
