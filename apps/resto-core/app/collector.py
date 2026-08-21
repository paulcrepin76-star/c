from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalog import record_catalog_quote
from app.geo import LOCAL_SUPPLIERS
from app.models import Connector, Supplier
from app.purchasing import match_canonical_product
from app.units import parse_pack

# How a price was collected. Never CAPTCHA, stealth, or proxy rotation.
ADAPTER_API = "api"
ADAPTER_PLAYWRIGHT = "playwright"
ADAPTER_AUTH = "auth_browser"
ADAPTER_EXTENSION = "extension"
ADAPTER_RECEIPT = "receipt"

SOURCE_CONFIDENCE = {
    "invoice": Decimal("1.00"),
    "extension": Decimal("0.95"),
    "auth_browser": Decimal("0.95"),
    "bls": Decimal("0.90"),
    "usda": Decimal("0.90"),
    "instacart": Decimal("0.90"),
    "catalog": Decimal("0.80"),
    "playwright": Decimal("0.80"),
    "open_prices": Decimal("0.70"),
}

SOURCE_LABEL = {
    "invoice": "Paid receipt",
    "extension": "Your browser",
    "auth_browser": "Saved session",
    "catalog": "Public website",
    "playwright": "Full browser",
    "open_prices": "Open Prices",
    "bls": "US retail average",
    "usda": "USDA wholesale",
    "instacart": "Instacart",
}

COLLECTORS: list[dict] = [
    {"slug": "webstaurantstore", "label": "WebstaurantStore", "adapter": ADAPTER_API, "status": "auto", "home": "https://www.webstaurantstore.com/", "blurb": "Public restaurant cases. Nightly HTML scan, no login."},
    {"slug": "open-prices", "label": "Open Prices", "adapter": ADAPTER_API, "status": "auto", "home": "https://prices.openfoodfacts.org/", "blurb": "Crowdsourced store prices, filtered around Bonita Springs first."},
    {"slug": "bls", "label": "US retail average (BLS)", "adapter": ADAPTER_API, "status": "auto", "home": "https://www.bls.gov/data/", "blurb": "Official US city-average retail. Benchmark only, not a store."},
    {"slug": "usda", "label": "USDA MyMarketNews", "adapter": ADAPTER_API, "status": "needs_key", "home": "https://mymarketnews.ams.usda.gov/", "blurb": "Wholesale dairy/meat. Add USDA_MMN_API_KEY when you have one."},
    {"slug": "instacart", "label": "Instacart", "adapter": ADAPTER_API, "status": "apply", "home": "https://www.instacart.com/", "hosts": ["instacart.com"], "blurb": "Nearby grocery prices after developer approval (~30–40 days). Not wired until Instacart says yes."},
    {"slug": "publix", "label": "Publix", "adapter": ADAPTER_PLAYWRIGHT, "status": "browser", "home": "https://www.publix.com/", "hosts": ["publix.com"], "blurb": "JS storefront. Full Chromium or the Chrome extension while you shop."},
    {"slug": "target", "label": "Target", "adapter": ADAPTER_PLAYWRIGHT, "status": "browser", "home": "https://www.target.com/", "hosts": ["target.com"], "blurb": "JS storefront. Full Chromium or the extension."},
    {"slug": "aldi", "label": "Aldi", "adapter": ADAPTER_PLAYWRIGHT, "status": "browser", "home": "https://www.aldi.us/", "hosts": ["aldi.us"], "blurb": "JS storefront. Full Chromium or the extension."},
    {"slug": "chefs-warehouse", "label": "Chef's Warehouse", "adapter": ADAPTER_AUTH, "status": "extension", "home": "https://shop.chefswarehouse.com/", "hosts": ["chefswarehouse.com"], "blurb": "You log in (2FA if asked). The extension reads the shop. Itemized PDFs stay the receipt of record."},
    {"slug": "gordon", "label": "Gordon Food Service", "adapter": ADAPTER_AUTH, "status": "extension", "home": "https://order.gfs.com/", "hosts": ["gfs.com", "order.gfs.com"], "blurb": "You log in on Gordon. Session cookies stay in your Chrome profile, not in git."},
    {"slug": "restaurant-depot", "label": "Restaurant Depot", "adapter": ADAPTER_AUTH, "status": "extension", "home": "https://www.restaurantdepot.com/", "hosts": ["restaurantdepot.com"], "blurb": "Member prices after you log in. Photograph the receipt for paid history."},
    {"slug": "sysco", "label": "Sysco", "adapter": ADAPTER_AUTH, "status": "extension", "home": "https://shop.sysco.com/", "hosts": ["sysco.com"], "blurb": "Customer portal. Extension while you are logged in — no password stored here."},
    {"slug": "us-foods", "label": "US Foods", "adapter": ADAPTER_AUTH, "status": "extension", "home": "https://www.usfoods.com/", "hosts": ["usfoods.com"], "blurb": "Customer portal. Same as Sysco: your browser, not a bot."},
    {"slug": "sams-club", "label": "Sam's Club", "adapter": ADAPTER_EXTENSION, "status": "extension", "home": "https://www.samsclub.com/", "hosts": ["samsclub.com"], "blurb": "Hard bot wall. Browse normally on your Mac; the extension sends visible packs. Receipts remain highest trust."},
    {"slug": "costco", "label": "Costco", "adapter": ADAPTER_EXTENSION, "status": "extension", "home": "https://www.costco.com/", "hosts": ["costco.com"], "blurb": "Same as Sam's: extension + receipts. Estero is the local warehouse."},
    {"slug": "walmart", "label": "Walmart", "adapter": ADAPTER_EXTENSION, "status": "extension", "home": "https://www.walmart.com/", "hosts": ["walmart.com"], "blurb": "No consumer grocery price API. Extension or a receipt, not Marketplace seller APIs."},
]


def adapter_label(adapter: str) -> str:
    return {
        ADAPTER_API: "AUTO — API / public feed",
        ADAPTER_PLAYWRIGHT: "AUTO — full browser",
        ADAPTER_AUTH: "AUTHENTICATED BROWSER",
        ADAPTER_EXTENSION: "BROWSER EXTENSION + RECEIPTS",
        ADAPTER_RECEIPT: "DOCUMENTS / receipts",
    }.get(adapter, adapter)


def collector_rows() -> list[dict]:
    return [
        {
            **source,
            "adapter_title": adapter_label(source["adapter"]),
        }
        for source in COLLECTORS
    ]


def source_label(source: str) -> str:
    return SOURCE_LABEL.get(source, source.replace("_", " ").title())


def confidence_for(source: str, purchased_on: date | None = None) -> Decimal:
    score = SOURCE_CONFIDENCE.get(source, Decimal("0.60"))
    if purchased_on and (date.today() - purchased_on).days > 90:
        score = min(score, Decimal("0.40"))
    return score


def _supplier_named(db: Session, name: str, city: str = "", miles=0) -> Supplier:
    label = name.strip()[:120]
    row = db.query(Supplier).filter(Supplier.name == label).first()
    if row is None:
        row = Supplier(name=label, category="food", default_invoice_type="food", city=(city or "")[:80], miles=Decimal(str(miles or 0)))
        local = LOCAL_SUPPLIERS.get(label)
        if local:
            row.city = row.city or local["city"]
            row.miles = row.miles or local["miles"]
        db.add(row)
        db.flush()
        return row
    if city and not row.city:
        row.city = city[:80]
    if miles and not row.miles:
        row.miles = Decimal(str(miles))
    return row


def ingest_collected_items(db: Session, payload: dict) -> dict:
    source = str(payload.get("source") or "extension")
    if source not in SOURCE_CONFIDENCE:
        source = "extension"
    supplier_name = str(payload.get("supplier") or "").strip()
    if not supplier_name:
        return {"status": "error", "error": "supplier is required", "recorded": 0}
    store = str(payload.get("store") or "").strip()
    miles = Decimal(str(payload.get("miles") or 0))
    captured = payload.get("captured_on") or payload.get("captured_at")
    scanned_on = date.fromisoformat(str(captured)[:10]) if captured else date.today()
    supplier = _supplier_named(db, supplier_name, city=store, miles=miles)
    recorded = 0
    skipped = 0
    for raw in payload.get("items") or []:
        name = str(raw.get("name") or raw.get("description") or "").strip()
        if not name:
            skipped += 1
            continue
        try:
            price = Decimal(str(raw.get("price") or raw.get("pack_price") or 0))
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        pack_text = " ".join(part for part in (name, str(raw.get("pack") or "")) if part)
        pack_qty, pack_unit = parse_pack(pack_text, raw.get("qty") or 0, str(raw.get("unit") or ""))
        if pack_qty <= 0 or price <= 0:
            skipped += 1
            continue
        product, _score = match_canonical_product(db, name)
        if product is None:
            skipped += 1
            continue
        url = str(raw.get("url") or payload.get("page_url") or "")[:400]
        row = record_catalog_quote(
            db,
            product,
            supplier,
            {
                "sku": str(raw.get("upc") or raw.get("sku") or "")[:80],
                "description": name[:240],
                "pack_qty": pack_qty,
                "pack_unit": pack_unit,
                "pack_price": price,
                "url": url,
                "miles": miles or supplier.miles or 0,
                "location_label": store or supplier.city or supplier.name,
                "is_discounted": bool(raw.get("discount") or raw.get("is_discounted")),
            },
            scanned_on,
            source=source,
        )
        if row:
            row.confidence = confidence_for(source, scanned_on)
            recorded += 1
    if recorded:
        connector = db.query(Connector).filter(Connector.name == supplier.name).first()
        if connector is None:
            connector = Connector(name=supplier.name, kind="catalog", status="ready")
            db.add(connector)
        connector.status = "ready"
        connector.notes = f"Last {source} capture {scanned_on.isoformat()} · {recorded} pack(s)"
        from datetime import UTC, datetime

        connector.last_run_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    return {"status": "ok", "recorded": recorded, "skipped": skipped, "supplier": supplier.name, "source": source}


_PRICE = re.compile(r"\$(\d+(?:\.\d{1,2})?)")


def extract_rendered_prices(html: str) -> list[dict]:
    """Read prices from rendered HTML (JSON-LD first). No login, no CAPTCHA."""
    found: list[dict] = []
    for raw in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        blocks = payload if isinstance(payload, list) else [payload]
        for block in blocks:
            found.extend(_ld_products(block))
    return found


def _ld_products(block) -> list[dict]:
    if not isinstance(block, dict):
        return []
    types = block.get("@type")
    type_list = types if isinstance(types, list) else [types]
    rows = []
    if any(str(item).lower() == "product" for item in type_list if item):
        offers = block.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price") if isinstance(offers, dict) else None
        name = str(block.get("name") or "").strip()
        if name and price:
            rows.append(
                {
                    "name": name[:240],
                    "price": Decimal(str(price)),
                    "pack": str(block.get("size") or block.get("description") or "")[:120],
                    "upc": str(block.get("sku") or block.get("gtin13") or block.get("gtin") or "")[:80],
                    "url": str((offers.get("url") if isinstance(offers, dict) else "") or block.get("url") or "")[:400],
                }
            )
    for value in block.values():
        if isinstance(value, dict):
            rows.extend(_ld_products(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    rows.extend(_ld_products(item))
    return rows


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def fetch_rendered_html(url: str, timeout_ms: int = 20000) -> str:
    """Optional Chromium fetch for public JS pages. Raises if Playwright is not installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()
        return html
