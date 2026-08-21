from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from app.costing import cost_percent, money
from app.models import Invoice, InvoiceLine, Product, ProductAlias, PurchasePrice, Recipe, RecipeLine, Supplier
from app.units import comparable_cost, parse_pack, to_base

STAY_THRESHOLD = Decimal("25")  # monthly saving below this: stay with the current supplier
BUTTER_EXCLUDES = ("peanut", "cacao", "cocoa", "hazelnut", "almond", "espelette", "buttermilk", "butternut")
CATEGORIES = ("", "dairy", "food", "meat", "produce", "cleaning", "beverage", "wine")
USAGE_DAYS = 30

CANONICAL_PRODUCTS = (
    {
        "sku": "BUTTER",
        "name": "Butter",
        "category": "dairy",
        "base_unit": "g",
        "compare_unit": "lb",
        "purchasing_category": "dairy",
        "excludes": BUTTER_EXCLUDES,
    },
    {
        "sku": "EGG",
        "name": "Eggs",
        "category": "dairy",
        "base_unit": "each",
        "compare_unit": "each",
        "purchasing_category": "dairy",
        "excludes": ("eggplant", "egg wash"),
    },
    {
        "sku": "MILK",
        "name": "Milk",
        "category": "dairy",
        "base_unit": "ml",
        "compare_unit": "gal",
        "purchasing_category": "dairy",
        "excludes": ("almond", "oat", "coconut", "buttermilk", "condensed"),
    },
    {
        "sku": "HEAVY-CREAM",
        "name": "Heavy cream",
        "category": "dairy",
        "base_unit": "ml",
        "compare_unit": "qt",
        "purchasing_category": "dairy",
        "excludes": ("ice cream", "creamer", "sour cream"),
    },
)

DEFAULT_ALIASES = (
    ("Butter", "butter", "peanut,cacao,cocoa,hazelnut,almond,espelette,buttermilk,butternut"),
    ("Butter", "unsalted butter", ""),
    ("Eggs", "egg", "eggplant,egg wash"),
    ("Eggs", "eggs", "eggplant"),
    ("Milk", "milk", "almond,oat,coconut,buttermilk,condensed"),
    ("Heavy cream", "heavy cream", "ice cream,creamer,sour cream"),
    ("Heavy cream", "whipping cream", ""),
)


def compare_unit_for(product: Product) -> str:
    return (product.compare_unit or product.base_unit or "g").strip() or "g"


def _has_alias(text: str, needle: str) -> bool:
    token = str(needle or "").lower().strip()
    if not token:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?:es|s)?(?![a-z0-9])", text) is not None


def _excluded(text: str, excludes) -> bool:
    return any(part and _has_alias(text, part) for part in excludes)


def match_canonical_product(db: Session, description: str) -> tuple[Product | None, Decimal]:
    text = str(description or "").lower()
    if not text.strip():
        return None, Decimal("0")
    aliases = db.query(ProductAlias).all()
    best: tuple[Product | None, Decimal] = (None, Decimal("0"))
    for alias in aliases:
        needle = alias.alias.lower().strip()
        if not _has_alias(text, needle):
            continue
        excluded = [part.strip() for part in (alias.exclude or "").split(",") if part.strip()]
        if _excluded(text, excluded):
            continue
        score = Decimal("0.95") if needle == text else Decimal("0.85")
        if len(needle) > 8:
            score += Decimal("0.05")
        if score > best[1]:
            best = (alias.product, score)
    if best[0]:
        return best
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    for product in products:
        name = product.name.lower().strip()
        if len(name) < 4 or not _has_alias(text, name):
            continue
        if "butter" in name and _excluded(text, BUTTER_EXCLUDES):
            continue
        return product, Decimal("0.6")
    return None, Decimal("0")


def record_line(db: Session, invoice: Invoice, line: InvoiceLine) -> PurchasePrice | None:
    if not invoice.supplier_id:
        return None
    if invoice.invoice_type not in ("food", "wine"):
        return None
    if "+$" in str(line.raw_description or ""):
        return None
    pack_price = Decimal(str(line.line_total or 0)) or (
        Decimal(str(line.qty or 0)) * Decimal(str(line.unit_cost or 0))
    )
    if pack_price <= 0:
        return None
    if line.product_id:
        product = db.get(Product, line.product_id)
        confidence = Decimal("1")
    else:
        product, confidence = match_canonical_product(db, line.raw_description)
    if product is None:
        return None
    if line.id and db.query(PurchasePrice).filter(PurchasePrice.invoice_line_id == line.id).first():
        return None
    pack_qty, pack_unit = parse_pack(line.raw_description, line.qty, line.unit)
    if pack_qty <= 0:
        return None
    compare_unit = compare_unit_for(product)
    unit_compare = comparable_cost(pack_price, pack_qty, pack_unit, compare_unit)
    qty_base = to_base(pack_qty, pack_unit, product.base_unit or compare_unit) or Decimal("0")
    unit_base = (pack_price / qty_base) if qty_base > 0 else Decimal("0")
    if unit_compare is None:
        return None
    row = PurchasePrice(
        product_id=product.id,
        supplier_id=invoice.supplier_id,
        invoice_id=invoice.id,
        invoice_line_id=line.id,
        purchased_on=invoice.issued_on,
        raw_description=str(line.raw_description or "")[:240],
        pack_qty=pack_qty,
        pack_unit=pack_unit,
        pack_price=pack_price,
        qty_base=qty_base,
        unit_cost_base=unit_base,
        compare_qty=to_base(pack_qty, pack_unit, compare_unit) or Decimal("0"),
        unit_cost_compare=unit_compare,
        confidence=confidence,
        source="invoice",
    )
    db.add(row)
    if line.product_id is None:
        line.product_id = product.id
    product.current_cost = unit_base
    return row


def record_invoice_prices(db: Session, invoice: Invoice) -> int:
    created = 0
    lines = db.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice.id).all()
    for line in lines:
        if record_line(db, invoice, line):
            created += 1
    if created:
        db.commit()
    return created


def backfill_purchase_prices(db: Session) -> int:
    created = 0
    invoices = db.query(Invoice).all()
    for invoice in invoices:
        for line in invoice.lines:
            if record_line(db, invoice, line):
                created += 1
    if created:
        db.commit()
    return created


def latest_by_supplier(db: Session, product_id: int) -> list[PurchasePrice]:
    rows = (
        db.query(PurchasePrice)
        .filter(PurchasePrice.product_id == product_id)
        .order_by(PurchasePrice.purchased_on.desc(), PurchasePrice.id.desc())
        .all()
    )
    seen: set[int] = set()
    latest = []
    for row in rows:
        if row.supplier_id in seen:
            continue
        seen.add(row.supplier_id)
        latest.append(row)
    return latest


def _cutoff(days: int) -> date:
    return date.today() - timedelta(days=days)


def monthly_usage_compare(db: Session, product: Product, days: int = USAGE_DAYS) -> Decimal:
    cutoff = _cutoff(days)
    total = Decimal("0")
    rows = db.query(PurchasePrice).filter(PurchasePrice.product_id == product.id).all()
    for row in rows:
        if row.purchased_on is None or row.purchased_on < cutoff:
            continue
        total += Decimal(str(row.compare_qty or 0))
    if days and days != 30:
        return money(total * Decimal(30) / Decimal(days))
    return total


def recipe_impacts(db: Session, product: Product, old_compare: Decimal, new_compare: Decimal) -> list[dict]:
    compare_unit = compare_unit_for(product)
    delta_per_compare = new_compare - old_compare
    impacts = []
    lines = db.query(RecipeLine).filter(RecipeLine.product_id == product.id).all()
    for line in lines:
        qty_compare = to_base(line.qty, line.unit, compare_unit)
        if qty_compare is None:
            continue
        recipe = db.get(Recipe, line.recipe_id)
        if not recipe:
            continue
        impacts.append(
            {
                "recipe": recipe.name,
                "delta": money(qty_compare * delta_per_compare),
            }
        )
    impacts.sort(key=lambda item: item["delta"])
    return impacts[:12]


def _volume_by_supplier(db: Session, product_id: int, days: int = USAGE_DAYS) -> dict[int, Decimal]:
    cutoff = _cutoff(days)
    volumes: dict[int, Decimal] = {}
    rows = db.query(PurchasePrice).filter(PurchasePrice.product_id == product_id).all()
    for row in rows:
        if row.purchased_on is None or row.purchased_on < cutoff:
            continue
        volumes[row.supplier_id] = volumes.get(row.supplier_id, Decimal("0")) + Decimal(str(row.compare_qty or 0))
    return volumes


def product_comparison(db: Session, product: Product) -> dict | None:
    latest = latest_by_supplier(db, product.id)
    if not latest:
        return None
    compare_unit = compare_unit_for(product)
    volumes = _volume_by_supplier(db, product.id)
    current = max(
        latest,
        key=lambda row: (
            volumes.get(row.supplier_id, Decimal("0")),
            row.purchased_on.toordinal() if row.purchased_on else 0,
        ),
    )
    cheapest = min(latest, key=lambda row: Decimal(str(row.unit_cost_compare)))
    gap = money(Decimal(str(current.unit_cost_compare)) - Decimal(str(cheapest.unit_cost_compare)))
    usage = monthly_usage_compare(db, product)
    monthly_unit = money(gap * usage) if usage else money(0)
    cheapest_supplier = cheapest.supplier
    current_supplier = current.supplier
    trip = Decimal(str(cheapest_supplier.trip_cost or 0)) if cheapest_supplier else Decimal("0")
    delivery = Decimal(str(cheapest_supplier.delivery_fee or 0)) if cheapest_supplier else Decimal("0")
    extra = trip + delivery
    if current_supplier and cheapest_supplier and cheapest_supplier.id != current_supplier.id:
        extra -= Decimal(str(current_supplier.delivery_fee or 0))
    net = money(monthly_unit - extra)
    recommend = "switch" if net >= STAY_THRESHOLD else "stay"
    if cheapest.supplier_id == current.supplier_id:
        recommend = "stay"
        net = money(0)
        monthly_unit = money(0)
        gap = money(0)
    return {
        "product": product,
        "compare_unit": compare_unit,
        "current": current,
        "cheapest": cheapest,
        "offers": sorted(latest, key=lambda row: Decimal(str(row.unit_cost_compare))),
        "gap": gap,
        "gap_pct": cost_percent(gap, current.unit_cost_compare),
        "usage": usage,
        "monthly": monthly_unit,
        "net": net,
        "trip_cost": trip,
        "delivery_fee": delivery,
        "min_order": Decimal(str(cheapest_supplier.min_order or 0)) if cheapest_supplier else Decimal("0"),
        "recommend": recommend,
        "impacts": recipe_impacts(
            db,
            product,
            Decimal(str(current.unit_cost_compare)),
            Decimal(str(cheapest.unit_cost_compare)),
        ),
    }


def purchasing_board(db: Session, category: str = "") -> dict:
    query = db.query(Product).filter(Product.is_active.is_(True))
    if category:
        query = query.filter(
            (Product.purchasing_category == category) | (Product.category == category)
        )
    cards = []
    monthly_total = Decimal("0")
    cheaper_elsewhere = 0
    for product in query.order_by(Product.name).all():
        card = product_comparison(db, product)
        if not card:
            continue
        cards.append(card)
        monthly_total += Decimal(str(card["net"] if card["recommend"] == "switch" else 0))
        if card["cheapest"].supplier_id != card["current"].supplier_id and card["gap"] > 0:
            cheaper_elsewhere += 1
    cards.sort(key=lambda item: Decimal(str(item["net"])), reverse=True)
    return {
        "cards": cards,
        "monthly_total": money(monthly_total),
        "cheaper_elsewhere": cheaper_elsewhere,
        "category": category,
        "stay_threshold": STAY_THRESHOLD,
    }


def board_payload(board: dict) -> dict:
    cards = []
    for card in board["cards"]:
        cards.append(
            {
                "product": card["product"].name,
                "sku": card["product"].sku,
                "category": card["product"].purchasing_category or card["product"].category,
                "compare_unit": card["compare_unit"],
                "current_supplier": card["current"].supplier.name if card["current"].supplier else "",
                "current_cost": float(card["current"].unit_cost_compare),
                "best_supplier": card["cheapest"].supplier.name if card["cheapest"].supplier else "",
                "best_cost": float(card["cheapest"].unit_cost_compare),
                "gap": float(card["gap"]),
                "gap_pct": float(card["gap_pct"]),
                "usage": float(card["usage"]),
                "monthly": float(card["monthly"]),
                "net": float(card["net"]),
                "recommend": card["recommend"],
                "offers": [
                    {
                        "supplier": row.supplier.name if row.supplier else "",
                        "pack": f"{row.pack_qty} {row.pack_unit}",
                        "pack_price": float(row.pack_price),
                        "unit_cost": float(row.unit_cost_compare),
                        "purchased_on": row.purchased_on.isoformat() if row.purchased_on else None,
                    }
                    for row in card["offers"]
                ],
                "impacts": [{"recipe": item["recipe"], "delta": float(item["delta"])} for item in card["impacts"]],
            }
        )
    return {
        "monthly_total": float(board["monthly_total"]),
        "cheaper_elsewhere": board["cheaper_elsewhere"],
        "category": board["category"],
        "cards": cards,
    }


def _find_canonical(db: Session, spec: dict) -> Product | None:
    product = db.query(Product).filter(Product.sku == spec["sku"]).first()
    if product:
        return product
    product = db.query(Product).filter(Product.name.ilike(spec["name"])).first()
    if product:
        return product
    excludes = spec.get("excludes") or ()
    matches = []
    for candidate in db.query(Product).filter(Product.name.ilike(f"%{spec['name']}%")).all():
        lowered = candidate.name.lower()
        if _excluded(lowered, excludes):
            continue
        matches.append(candidate)
    if matches:
        return min(matches, key=lambda item: len(item.name))
    return None


def ensure_purchasing(db: Session) -> None:
    by_name: dict[str, Product] = {}
    for spec in CANONICAL_PRODUCTS:
        product = _find_canonical(db, spec)
        if product is None:
            product = Product(
                sku=spec["sku"],
                name=spec["name"],
                category=spec["category"],
                base_unit=spec["base_unit"],
            )
            db.add(product)
            db.flush()
        product.compare_unit = product.compare_unit or spec["compare_unit"]
        product.purchasing_category = product.purchasing_category or spec["purchasing_category"]
        if product.category in ("", "food"):
            product.category = spec["category"]
        by_name[spec["name"].lower()] = product
    db.flush()
    for name, alias, exclude in DEFAULT_ALIASES:
        product = by_name.get(name.lower())
        if product is None:
            continue
        exists = (
            db.query(ProductAlias)
            .filter(ProductAlias.product_id == product.id, ProductAlias.alias == alias)
            .first()
        )
        if exists:
            continue
        db.add(ProductAlias(product_id=product.id, alias=alias, exclude=exclude))
    db.commit()
