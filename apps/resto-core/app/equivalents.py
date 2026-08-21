from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    CatalogItem,
    Connection,
    InvoiceLine,
    Product,
    ProductAlias,
    ProductEquivalent,
    PurchasePrice,
    RecipeLine,
    Supplier,
)
from app.purchasing import CANONICAL_PRODUCTS, match_canonical_product
from app.units import parse_pack

SKU_RE = re.compile(
    r"\b(?:sku|item(?:\s*(?:#|no\.?|number))?|upc)\s*[:#]?\s*([A-Z0-9-]{3,})\b",
    re.I,
)
SKIP_CATEGORIES = {"wine"}
REFRESH_PRODUCT_CAP = 40
DISCOVERY_PRODUCT_CAP = 80
NAME_KEYS = ("name", "title", "productName", "description", "alt")
PRICE_KEYS = ("price", "salePrice", "currentPrice", "finalPrice", "listPrice", "amount", "lowPrice")
SKU_KEYS = ("sku", "itemNumber", "itemId", "item_id", "productId", "product_id", "upc", "gtin", "gtin13")
BRAND_KEYS = ("brand", "brandName", "manufacturer")


def extract_sku(text: str) -> str:
    match = SKU_RE.search(str(text or ""))
    return (match.group(1) if match else "")[:80]


def _price_amount(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in PRICE_KEYS:
            if value.get(key) not in (None, ""):
                return _price_amount(value.get(key))
        return None
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None
    return amount if amount > 0 else None


def _first_str(obj: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, dict) and "name" in value:
            value = value.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def walk_json_products(payload, found: list[dict] | None = None, depth: int = 0) -> list[dict]:
    """Pull product-shaped objects out of a site's own JSON (XHR, Next.js, script tags)."""
    if found is None:
        found = []
    if depth > 10 or len(found) >= 250:
        return found
    if isinstance(payload, list):
        for item in payload:
            walk_json_products(item, found, depth + 1)
        return found
    if not isinstance(payload, dict):
        return found
    name = _first_str(payload, NAME_KEYS)
    offers = payload.get("offers")
    price = _price_amount(payload.get("salePrice") or payload.get("finalPrice") or payload.get("price"))
    if price is None and isinstance(offers, dict):
        price = _price_amount(offers)
    elif price is None and isinstance(offers, list) and offers:
        price = _price_amount(offers[0] if isinstance(offers[0], dict) else None)
    sku = _first_str(payload, SKU_KEYS)
    if name and price is not None and len(name) >= 4:
        promo = _price_amount(payload.get("salePrice") or payload.get("finalPrice"))
        regular = _price_amount(payload.get("listPrice") or payload.get("regularPrice") or payload.get("price")) or price
        pack_text = " ".join(part for part in (name, str(payload.get("size") or payload.get("pack") or payload.get("packSize") or "")) if part)
        pack_qty, pack_unit = parse_pack(pack_text)
        case_qty = Decimal("0")
        units = payload.get("unitsPerPackaging") or payload.get("caseQty") or payload.get("caseQuantity")
        if units:
            try:
                case_qty = Decimal(str(units))
            except Exception:  # noqa: BLE001
                case_qty = Decimal("0")
        found.append(
            {
                "description": name[:240],
                "sku": sku[:80],
                "upc": _first_str(payload, ("upc", "gtin", "gtin13"))[:80],
                "brand": _first_str(payload, BRAND_KEYS)[:120],
                "pack_price": promo or price,
                "regular_price": regular,
                "promo_price": promo or Decimal("0"),
                "pack_qty": pack_qty,
                "pack_unit": pack_unit,
                "case_qty": case_qty,
                "url": str(payload.get("url") or payload.get("link") or payload.get("canonicalUrl") or "")[:400],
                "available": payload.get("available", payload.get("inStock", True)) is not False,
                "is_discounted": bool(promo and regular and promo < regular),
            }
        )
    for value in payload.values():
        if isinstance(value, (dict, list)):
            walk_json_products(value, found, depth + 1)
    return found


def dedupe_products(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for item in items:
        key = str(item.get("sku") or "") or f"{item.get('description')}|{item.get('pack_price')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def grocery_product(product: Product) -> bool:
    category = (product.purchasing_category or product.category or "").lower()
    return category not in SKIP_CATEGORIES


def relevant_products(db: Session, mode: str = "refresh") -> list[Product]:
    """What the cafe actually buys: invoices, receipts, extension captures, Mealie lines."""
    ids: set[int] = set()
    for (product_id,) in db.query(InvoiceLine.product_id).filter(InvoiceLine.product_id.isnot(None)).distinct():
        ids.add(int(product_id))
    for (product_id,) in (
        db.query(PurchasePrice.product_id)
        .filter(PurchasePrice.source.in_(("invoice", "extension", "auth_browser")))
        .distinct()
    ):
        ids.add(int(product_id))
    for (product_id,) in db.query(RecipeLine.product_id).distinct():
        ids.add(int(product_id))
    for (product_id,) in db.query(ProductEquivalent.product_id).distinct():
        ids.add(int(product_id))
    if mode == "discovery":
        skus = [spec["sku"] for spec in CANONICAL_PRODUCTS]
        for product in db.query(Product).filter(Product.sku.in_(skus)).all():
            ids.add(product.id)
    products = (
        db.query(Product)
        .filter(Product.id.in_(ids or {-1}), Product.is_active.is_(True))
        .order_by(Product.name)
        .all()
    )
    grocery = [product for product in products if grocery_product(product)]
    cap = DISCOVERY_PRODUCT_CAP if mode == "discovery" else REFRESH_PRODUCT_CAP
    return grocery[:cap]


def search_queries(db: Session, product: Product, mode: str = "refresh") -> list[str]:
    aliases = [
        alias.alias.strip()
        for alias in db.query(ProductAlias).filter(ProductAlias.product_id == product.id).all()
        if alias.alias.strip()
    ]
    queries: list[str] = []
    for candidate in [product.name, *aliases]:
        text = str(candidate or "").strip().lower()
        if text and text not in queries:
            queries.append(text)
    limit = 4 if mode == "discovery" else 2
    return queries[:limit]


def match_by_sku(db: Session, supplier: Supplier, sku: str) -> Product | None:
    code = str(sku or "").strip()
    if not code:
        return None
    row = (
        db.query(ProductEquivalent)
        .filter(ProductEquivalent.supplier_id == supplier.id, ProductEquivalent.sku == code[:80])
        .first()
    )
    return row.product if row else None


def resolve_product(db: Session, supplier: Supplier, description: str, sku: str = "") -> Product | None:
    matched = match_by_sku(db, supplier, sku)
    if matched:
        return matched
    product, _score = match_canonical_product(db, description)
    return product


def upsert_equivalent(
    db: Session,
    product: Product,
    supplier: Supplier,
    item: dict,
    seen_on: date | None = None,
    source: str = "catalog",
) -> ProductEquivalent | None:
    sku = str(item.get("sku") or extract_sku(str(item.get("description") or "")))[:80]
    if not sku:
        return None
    row = (
        db.query(ProductEquivalent)
        .filter(ProductEquivalent.supplier_id == supplier.id, ProductEquivalent.sku == sku)
        .first()
    )
    if row is None:
        row = ProductEquivalent(product_id=product.id, supplier_id=supplier.id, sku=sku)
        db.add(row)
    row.product_id = product.id
    row.upc = str(item.get("upc") or row.upc or "")[:80]
    row.brand = str(item.get("brand") or row.brand or "")[:120]
    row.description = str(item.get("description") or row.description or "")[:240]
    pack_qty = Decimal(str(item.get("pack_qty") or row.pack_qty or 0))
    pack_unit = str(item.get("pack_unit") or row.pack_unit or "")
    if pack_qty > 0:
        row.pack_qty = pack_qty
    if pack_unit:
        row.pack_unit = pack_unit
    case_qty = Decimal(str(item.get("case_qty") or 0))
    if case_qty > 0:
        row.case_qty = case_qty
    price = Decimal(str(item.get("pack_price") or item.get("last_price") or 0))
    if price > 0:
        row.last_price = price
    row.last_seen = seen_on or date.today()
    row.source = source
    row.url = str(item.get("url") or row.url or "")[:400]
    db.flush()
    return row


def store_catalog_item(
    db: Session,
    supplier: Supplier,
    item: dict,
    captured_on: date,
    product: Product | None = None,
    source: str = "catalog",
    scan_mode: str = "refresh",
) -> CatalogItem | None:
    sku = str(item.get("sku") or extract_sku(str(item.get("description") or "")))[:80]
    if not sku:
        sku = str(item.get("description") or "item")[:80]
    regular = Decimal(str(item.get("regular_price") or item.get("pack_price") or 0))
    promo = Decimal(str(item.get("promo_price") or 0))
    pack_price = Decimal(str(item.get("pack_price") or promo or regular or 0))
    row = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.supplier_id == supplier.id,
            CatalogItem.sku == sku,
            CatalogItem.captured_on == captured_on,
        )
        .first()
    )
    if row is None:
        row = CatalogItem(supplier_id=supplier.id, sku=sku, captured_on=captured_on)
        db.add(row)
    row.product_id = product.id if product else row.product_id
    row.upc = str(item.get("upc") or "")[:80]
    row.brand = str(item.get("brand") or "")[:120]
    row.description = str(item.get("description") or "")[:240]
    row.pack_qty = Decimal(str(item.get("pack_qty") or 0))
    row.pack_unit = str(item.get("pack_unit") or "")[:20]
    row.case_qty = Decimal(str(item.get("case_qty") or 0))
    row.regular_price = regular or pack_price
    row.promo_price = promo
    row.location_label = str(item.get("location_label") or supplier.city or "")[:160]
    row.available = bool(item.get("available", True))
    row.source = source
    row.scan_mode = scan_mode
    row.url = str(item.get("url") or "")[:400]
    db.flush()
    return row


def equivalents_for(db: Session, product: Product) -> list[ProductEquivalent]:
    return (
        db.query(ProductEquivalent)
        .filter(ProductEquivalent.product_id == product.id)
        .order_by(ProductEquivalent.supplier_id, ProductEquivalent.sku)
        .all()
    )


def connection_status(db: Session, slug: str) -> str:
    row = db.query(Connection).filter(Connection.name == slug).first()
    return row.status if row else "not_connected"


def watch_payload(db: Session) -> dict:
    products = relevant_products(db, mode="refresh")
    rows = []
    for product in products:
        aliases = [
            alias.alias.lower()
            for alias in db.query(ProductAlias).filter(ProductAlias.product_id == product.id).all()
        ]
        needles = []
        for text in [product.name, product.sku, *aliases]:
            token = str(text or "").strip().lower()
            if token and token not in needles:
                needles.append(token)
        supplier_skus = {}
        for equivalent in equivalents_for(db, product):
            if equivalent.sku and equivalent.supplier:
                supplier_skus[equivalent.supplier.name] = equivalent.sku
                needles.append(equivalent.sku.lower())
        rows.append(
            {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "needles": needles,
                "supplier_skus": supplier_skus,
            }
        )
    return {"count": len(rows), "products": rows}
