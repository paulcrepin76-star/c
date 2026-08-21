import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.costing import money
from app.models import Invoice, InvoiceLine, Product, Recipe, RecipeLine, Sale, SellableItem, StockMove, Supplier
from app.units import family, parse_pack
from app.vendors import VENDORS, vendor_names

_PRICE = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")
_SKIP_LINE = re.compile(
    r"\b(subtotal|total due|invoice total|amount due|balance due|sales tax|payment|invoice\s*#)\b",
    re.I,
)
_QTY_LINE = re.compile(r"^Qty\s+(\d+(?:\.\d+)?)$", re.I)
_PRICE_LINE = re.compile(r"^\$(\d{1,3}(?:,\d{3})*\.\d{2})$")
_PER_UNIT = re.compile(r"^\$?\d+(?:\.\d+)?\s*/|^\d+(?:\.\d+)?¢/")


def _line_item(description: str, qty: Decimal, unit: str, price: Decimal) -> dict:
    return {
        "description": description[:240],
        "qty": qty,
        "unit": unit,
        "unit_cost": Decimal("0"),
        "line_total": price,
    }


def _single_line_item(text: str) -> dict | None:
    if len(text) < 8 or _SKIP_LINE.search(text):
        return None
    pack_qty, pack_unit = parse_pack(text)
    if pack_qty <= 0 or not pack_unit or family(pack_unit) is None:
        return None
    prices = [money(item.replace(",", "")) for item in _PRICE.findall(text)]
    if not prices:
        return None
    price = max(prices)
    if price <= 0:
        return None
    return _line_item(text, pack_qty, pack_unit, price)


def _multiline_item(lines: list[str], index: int) -> tuple[dict, int] | None:
    if index + 2 >= len(lines):
        return None
    desc = lines[index]
    if _SKIP_LINE.search(desc) or _QTY_LINE.match(desc) or _PRICE_LINE.match(desc):
        return None
    pack_qty, pack_unit = parse_pack(desc)
    if pack_qty <= 0 or family(pack_unit) is None:
        return None
    cursor = index + 1
    if cursor < len(lines) and _PER_UNIT.search(lines[cursor]):
        cursor += 1
    qty_match = _QTY_LINE.match(lines[cursor]) if cursor < len(lines) else None
    if not qty_match:
        return None
    multiplier = Decimal(qty_match.group(1))
    cursor += 1
    price_match = _PRICE_LINE.match(lines[cursor]) if cursor < len(lines) else None
    if not price_match:
        return None
    price = money(price_match.group(1).replace(",", ""))
    if price <= 0 or multiplier <= 0:
        return None
    item = _line_item(f"{desc} Qty {multiplier}", pack_qty * multiplier, pack_unit, price)
    return item, cursor - index + 1


def ocr_is_usable(content: str) -> bool:
    """Skip faded / erased scans instead of inventing line items from garbage OCR."""
    text = str(content or "")
    words = re.findall(r"[A-Za-z]{3,}", text)
    letters = sum(ch.isalpha() for ch in text)
    if letters < 24:
        return False
    if len(text) >= 300 and len(words) < 15 and letters / len(text) < 0.25:
        return False
    if len(text) >= 400 and letters / len(text) < 0.12:
        return False
    prices = bool(re.search(r"\d+\.\d{2}", text))
    packs = bool(re.search(r"\b\d+\s*[x/]\s*\d+\b|\b\d+/1\s*lb\b|\b12/750\b", text, re.I))
    if prices and (packs or len(words) >= 8):
        return True
    return len(words) >= 18 and letters >= 80


def extract_invoice_lines(content: str) -> list[dict]:
    """Pull pack + price rows out of Paperless OCR. Totals and tax lines are skipped."""
    rows = [" ".join(part.split()) for part in str(content or "").splitlines()]
    rows = [row for row in rows if row]
    found: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    index = 0
    while index < len(rows):
        block = _multiline_item(rows, index)
        item = None
        consumed = 1
        if block:
            item, consumed = block
        else:
            item = _single_line_item(rows[index])
        if item:
            key = (str(item["qty"]), item["unit"], str(item["line_total"]))
            if key not in seen:
                seen.add(key)
                found.append(item)
        index += consumed
    return found


_DOLLAR = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})")
_LABELED = re.compile(
    r"(?:invoice\s+total|amount\s+due|balance\s+due|total\s+due|\btotal\b|\bamount\b|\bbalance\b)"
    r"[^\d$]{0,24}(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})",
    re.I,
)


def parse_invoice_amount(*parts) -> Decimal:
    blob = " ".join(str(part or "") for part in parts)
    if not blob.strip():
        return Decimal("0")
    dollars = _DOLLAR.findall(blob)
    if dollars:
        return money(dollars[-1].replace(",", ""))
    labeled = _LABELED.findall(blob)
    if labeled:
        return money(labeled[-1].replace(",", ""))
    return Decimal("0")


def coerce_money(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, (int, float)):
        return money(value)
    text = str(value).strip()
    parsed = parse_invoice_amount(text)
    if parsed:
        return parsed
    cleaned = text.replace("$", "").replace(",", "").replace("USD", "").strip()
    try:
        return money(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def match_supplier(db: Session, correspondent: str | None, invoice_type: str = "food") -> Supplier | None:
    if not correspondent:
        return None
    name = str(correspondent).strip()
    supplier = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if supplier:
        return supplier
    lowered = name.lower()
    for vendor in VENDORS:
        aliases = [item.lower() for item in vendor_names(vendor)]
        if any(alias in lowered or lowered in alias for alias in aliases):
            supplier = db.query(Supplier).filter(Supplier.name == vendor["label"]).first()
            if supplier:
                return supplier
    supplier = Supplier(name=name, category=invoice_type, default_invoice_type=invoice_type)
    db.add(supplier)
    db.flush()
    return supplier


def clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_food_name(raw: str) -> str:
    text = str(raw or "").strip()
    if "REVIEW REQUIRED" in text.upper():
        text = text.split("REVIEW REQUIRED")[0]
        text = text.split("review required")[0]
    text = text.split("·")[0]
    text = text.replace("/", " ")
    text = " ".join(text.split()).strip(" -·,;")
    return clip(text, 180)


def product_sku(food: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in food.upper())
    slug = "-".join(part for part in slug.split("-") if part)
    return clip(slug or "FOOD", 70)


def match_sellable(db: Session, name: str, square_item_id: str = "") -> SellableItem | None:
    if square_item_id:
        item = db.query(SellableItem).filter(SellableItem.square_item_id == square_item_id).first()
        if item:
            return item
    return db.query(SellableItem).filter(SellableItem.name.ilike(name)).first()


def ingest_sales(db: Session, sales: list[dict]) -> dict:
    created = 0
    skipped = 0
    for incoming in sales:
        order_id = str(incoming.get("square_order_id") or "")
        line_id = str(incoming.get("square_line_id") or incoming.get("name") or "")
        if order_id and line_id:
            exists = db.query(Sale).filter(Sale.square_order_id == order_id, Sale.square_line_id == line_id).first()
            if exists:
                skipped += 1
                continue
        name = str(incoming.get("name") or "Item")
        item = match_sellable(db, name, str(incoming.get("square_item_id") or ""))
        qty = Decimal(str(incoming.get("qty") or 1))
        unit_price = Decimal(str(incoming.get("unit_price") or 0))
        revenue = incoming.get("revenue")
        revenue = Decimal(str(revenue)) if revenue is not None else unit_price * qty
        sold_at = incoming.get("sold_at")
        if isinstance(sold_at, str):
            sold_at = datetime.fromisoformat(sold_at.replace("Z", "+00:00")).replace(tzinfo=None)
        elif getattr(sold_at, "tzinfo", None):
            sold_at = sold_at.replace(tzinfo=None)
        if item is None:
            item = SellableItem(
                name=name,
                costing_group=str(incoming.get("costing_group") or "food"),
                selling_price=unit_price,
                square_item_id=str(incoming.get("square_item_id") or ""),
            )
            db.add(item)
            db.flush()
        sale = Sale(
            sold_at=sold_at,
            sellable_item_id=item.id,
            qty=qty,
            unit_price=unit_price,
            revenue=revenue,
            square_order_id=order_id,
            square_line_id=line_id,
        )
        db.add(sale)
        db.flush()
        if item.product_id and item.serving_unit == "ml":
            db.add(
                StockMove(
                    product_id=item.product_id,
                    occurred_at=sold_at,
                    qty_base=-(Decimal(item.serving_qty) * qty),
                    reason="sale",
                    location="bar",
                    sale_id=sale.id,
                )
            )
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


def _invoice_total(doc: dict) -> Decimal:
    total = coerce_money(doc.get("total"))
    if total > 0:
        return total
    return parse_invoice_amount(doc.get("title"), doc.get("content"), doc.get("correspondent"))


def _add_invoice_lines(db: Session, invoice: Invoice, lines: list[dict], require_match: bool = False) -> int:
    from app.purchasing import match_canonical_product

    added = 0
    for line in lines:
        description = str(line.get("description") or line.get("raw_description") or "")
        if not description:
            continue
        if require_match and match_canonical_product(db, description)[0] is None:
            continue
        item = InvoiceLine(
            invoice_id=invoice.id,
            raw_description=description[:240],
            qty=Decimal(str(line.get("qty") or 0)),
            unit=str(line.get("unit") or "each")[:20],
            unit_cost=Decimal(str(line.get("unit_cost") or 0)),
            line_total=Decimal(str(line.get("line_total") or 0)),
        )
        invoice.lines.append(item)
        db.add(item)
        added += 1
    if added:
        db.flush()
    return added


def _ocr_lines_for(db: Session, invoice: Invoice, doc: dict) -> list[dict]:
    if invoice.invoice_type not in ("food", "wine"):
        return []
    if not doc.get("lines") and not ocr_is_usable(str(doc.get("content") or "")):
        return []
    existing = {
        str(line.raw_description or "")
        for line in db.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice.id).all()
    }
    found: list[dict] = []
    for item in list(doc.get("lines") or []) + extract_invoice_lines(str(doc.get("content") or "")):
        description = str(item.get("description") or item.get("raw_description") or "")
        if not description or description in existing:
            continue
        found.append(item)
        existing.add(description)
    return found


def ingest_paperless_doc(db: Session, doc: dict) -> dict:
    from app.purchasing import record_invoice_prices

    paperless_id = str(doc.get("id") or "")
    invoice_type = str(doc.get("invoice_type") or "food")
    total = _invoice_total(doc)
    existing = db.query(Invoice).filter(Invoice.paperless_id == paperless_id).first()
    if existing:
        status = "duplicate"
        if Decimal(existing.total or 0) == 0 and total > 0:
            existing.total = total
            status = "updated"
        if not existing.supplier_id:
            supplier = match_supplier(db, doc.get("correspondent"), invoice_type)
            if supplier:
                existing.supplier_id = supplier.id
                status = "updated"
        if doc.get("title") and not existing.title:
            existing.title = str(doc.get("title") or "")[:240]
            status = "updated"
        parsed = _ocr_lines_for(db, existing, doc)
        if _add_invoice_lines(db, existing, parsed, require_match=not doc.get("lines")):
            status = "updated"
        if status == "updated":
            db.commit()
            record_invoice_prices(db, existing)
        return {"status": status, "invoice_id": existing.id}
    supplier = match_supplier(db, doc.get("correspondent"), invoice_type)
    issued_on = None
    created = doc.get("created")
    if created:
        try:
            issued_on = datetime.fromisoformat(str(created).replace("Z", "")).date()
        except ValueError:
            issued_on = None
    invoice = Invoice(
        supplier_id=supplier.id if supplier else None,
        paperless_id=paperless_id,
        number=str(doc.get("invoice_number") or ""),
        issued_on=issued_on,
        total=total,
        invoice_type=invoice_type,
        status="filed",
        title=str(doc.get("title") or "")[:240],
    )
    db.add(invoice)
    db.flush()
    _add_invoice_lines(db, invoice, _ocr_lines_for(db, invoice, doc), require_match=not doc.get("lines"))
    db.commit()
    record_invoice_prices(db, invoice)
    return {"status": "created", "invoice_id": invoice.id}


def ingest_recipes(db: Session, recipes: list[dict]) -> dict:
    created = 0
    updated = 0
    for incoming in recipes:
        name = clip(str(incoming.get("name") or "").strip().split("·")[0].strip(), 200)
        if not name:
            continue
        mealie_id = clip(str(incoming.get("mealie_id") or ""), 80)
        recipe = db.query(Recipe).filter(Recipe.mealie_id == mealie_id).first() if mealie_id else None
        if recipe is None:
            recipe = db.query(Recipe).filter(Recipe.name.ilike(name)).first()
        if recipe is None:
            recipe = Recipe(name=name, mealie_id=mealie_id, yield_qty=incoming.get("yield_qty") or 1, yield_unit=clip(str(incoming.get("yield_unit") or "portion"), 20) or "portion")
            db.add(recipe)
            db.flush()
            created += 1
        else:
            recipe.name = name
            recipe.mealie_id = mealie_id or recipe.mealie_id
            updated += 1
            db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe.id).delete()
        for line in incoming.get("lines") or []:
            food = clean_food_name(str(line.get("name") or line.get("food") or ""))
            if not food:
                continue
            product = db.query(Product).filter(Product.name.ilike(food)).first()
            if product is None:
                sku = product_sku(food)
                taken = db.query(Product).filter(Product.sku == sku).first()
                if taken:
                    product = taken
                else:
                    product = Product(
                        sku=sku,
                        name=food,
                        category="food",
                        base_unit=clip(str(line.get("unit") or "g"), 20) or "g",
                    )
                    db.add(product)
                    db.flush()
            db.add(
                RecipeLine(
                    recipe_id=recipe.id,
                    product_id=product.id,
                    qty=line.get("qty") or 0,
                    unit=clip(str(line.get("unit") or "g"), 20) or "g",
                )
            )
        price = incoming.get("selling_price")
        if price is not None:
            item = db.query(SellableItem).filter(SellableItem.recipe_id == recipe.id).first()
            if item is None:
                item = SellableItem(
                    recipe_id=recipe.id,
                    name=clip(name, 200),
                    costing_group=incoming.get("costing_group") or "food",
                )
                db.add(item)
            item.selling_price = price
            item.name = clip(name, 200)
    db.commit()
    return {"created": created, "updated": updated}
