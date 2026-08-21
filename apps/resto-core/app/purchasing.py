from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from app.costing import cost_percent, money
from app.geo import FAR_MILES, HOME_MARKET, LOCAL_SUPPLIERS, MID_MILES, NEAR_MILES, radius_band
from app.models import Invoice, InvoiceLine, Product, ProductAlias, PurchasePrice, Recipe, RecipeLine, Supplier
from app.units import comparable_cost, family, parse_pack, to_base

STAY_THRESHOLD = Decimal("25")  # monthly saving below this: stay with the current supplier
GAP_PCT_THRESHOLD = Decimal("8")  # also require 8% cheaper so $0.03 gaps do not alert
PAID_SOURCES = ("invoice",)
ACCOUNT_SOURCES = ("extension", "auth_browser")
PUBLIC_SOURCES = ("catalog", "open_prices", "playwright")
BENCHMARK_SOURCES = ("bls", "usda")
BUTTER_EXCLUDES = (
    "peanut",
    "cacao",
    "cocoa",
    "hazelnut",
    "almond",
    "cashew",
    "pecan",
    "pistachio",
    "walnut",
    "nut butter",
    "espelette",
    "buttermilk",
    "butternut",
    "vegan",
    "plant-based",
    "margarine",
    "clarified",
    "lamination",
    "whipped",
    "portion",
    "foiled",
    "chip",
)
CATEGORIES = ("", "dairy", "food", "meat", "produce", "cleaning", "beverage", "wine")
USAGE_DAYS = 30
COMPARE_DAYS = (30, 60, 90, 365)
DEFAULT_COMPARE_DAYS = 90
VENDOR_ORDER = (
    "Chef's Warehouse",
    "Gordon Food Service",
    "Sam's Club",
    "Costco",
    "Publix",
    "Restaurant Depot",
    "ALDI",
    "WebstaurantStore",
    "PG Fine Wines",
    "Stan's Coffee",
    "St. Armands Baking Company",
)
VENDOR_SHORT = {
    "Chef's Warehouse": "Chef's",
    "Gordon Food Service": "Gordon",
    "Sam's Club": "Sam's",
    "Restaurant Depot": "Depot",
    "WebstaurantStore": "Webstaurant",
    "PG Fine Wines": "PG Wines",
    "St. Armands Baking Company": "Armands",
    "Stan's Coffee": "Stan's",
    "US retail average (BLS)": "BLS",
}

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
        "excludes": ("almond", "oat", "coconut", "buttermilk", "condensed", "yogurt"),
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
    {
        "sku": "SALMON",
        "name": "Salmon",
        "category": "meat",
        "base_unit": "g",
        "compare_unit": "lb",
        "purchasing_category": "meat",
        "excludes": ("oil", "seasoning"),
    },
    {
        "sku": "CHICKEN",
        "name": "Chicken",
        "category": "meat",
        "base_unit": "g",
        "compare_unit": "lb",
        "purchasing_category": "meat",
        "excludes": ("stock", "broth", "seasoning", "nugget"),
    },
)

DEFAULT_ALIASES = (
    ("Butter", "butter", "peanut,cacao,cocoa,hazelnut,almond,cashew,pecan,pistachio,walnut,nut butter,espelette,buttermilk,butternut,vegan,plant-based,margarine,clarified,lamination,whipped,portion,foiled,chip"),
    ("Butter", "unsalted butter", "vegan,plant-based,clarified,nut butter,cashew,pecan,pistachio,lamination"),
    ("Eggs", "egg", "eggplant,egg wash"),
    ("Eggs", "eggs", "eggplant"),
    ("Milk", "milk", "almond,oat,coconut,buttermilk,condensed,yogurt"),
    ("Heavy cream", "heavy cream", "ice cream,creamer,sour cream"),
    ("Heavy cream", "whipping cream", ""),
    ("Salmon", "salmon", "oil,seasoning"),
    ("Chicken", "chicken", "stock,broth,seasoning,nugget"),
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
        related = [alias for alias in aliases if alias.product_id == product.id]
        if any(
            _excluded(text, [part.strip() for part in (alias.exclude or "").split(",") if part.strip()])
            for alias in related
        ):
            continue
        if "butter" in name and _excluded(text, BUTTER_EXCLUDES):
            continue
        return product, Decimal("0.6")
    return None, Decimal("0")


SKIP_NEW_PRODUCT = (
    "tax",
    "subtotal",
    "total",
    "payment",
    "visa",
    "mastercard",
    "change",
    "cash",
    "tip",
    "deposit",
    "fee",
    "archived",
    "authenticated",
    "order history",
    "order detail",
    "account dashboard",
)


def ensure_purchased_product(db: Session, description: str) -> Product | None:
    """Create a watch-list product from a new invoice line the cafe actually bought."""
    from app.ingest import clean_food_name, product_sku

    text = str(description or "").strip()
    lowered = text.lower()
    if len(re.findall(r"[a-zA-Z]", text)) < 4:
        return None
    if len(re.findall(r"[A-Za-z]{3,}", text)) < 1:
        return None
    if re.match(r"^\d{8,}\b", text):
        return None
    if any(_has_alias(lowered, word) for word in SKIP_NEW_PRODUCT):
        return None
    text = re.sub(r"\s+Qty\s+\d+(?:\.\d+)?\s*$", "", text, flags=re.I).strip()
    food = clean_food_name(re.sub(r"\b(?:sku|upc)\s*[:#]?\s*[A-Z0-9-]+\b", "", text, flags=re.I)) or text
    food = food[:80].strip(" -")
    if len(food) < 4:
        return None
    sku = product_sku(food)
    existing = db.query(Product).filter(Product.sku == sku).first()
    if existing:
        return existing
    named = db.query(Product).filter(Product.name.ilike(food)).first()
    if named:
        return named
    pack_qty, pack_unit = parse_pack(text)
    product = Product(
        sku=sku,
        name=food[:200],
        category="food",
        base_unit=pack_unit if pack_unit in {"g", "ml", "each", "lb", "floz"} else (pack_unit or "each"),
        compare_unit=pack_unit or "each",
        purchasing_category="food",
        is_active=True,
    )
    db.add(product)
    db.flush()
    db.add(ProductAlias(product_id=product.id, alias=food.lower()[:160], exclude=""))
    return product


def _is_purchasing_supplier(supplier: Supplier | None) -> bool:
    if supplier is None:
        return False
    from app.vendors import VENDORS, vendor_names

    name = supplier.name.lower()
    for vendor in VENDORS:
        if vendor.get("invoice_type") not in ("food", "wine"):
            continue
        aliases = [item.lower() for item in vendor_names(vendor)]
        if name in aliases or any(alias and alias in name for alias in aliases):
            return True
        if any(needle and needle in name for needle in vendor.get("match_needles") or []):
            return True
    return False


def record_line(db: Session, invoice: Invoice, line: InvoiceLine) -> PurchasePrice | None:
    if not invoice.supplier_id:
        return None
    if invoice.invoice_type not in ("food", "wine"):
        return None
    supplier = invoice.supplier or db.get(Supplier, invoice.supplier_id)
    if not _is_purchasing_supplier(supplier):
        return None
    if "+$" in str(line.raw_description or ""):
        return None
    pack_price = Decimal(str(line.line_total or 0)) or (
        Decimal(str(line.qty or 0)) * Decimal(str(line.unit_cost or 0))
    )
    if pack_price <= 0:
        return None
    from app.equivalents import extract_sku, upsert_equivalent

    sku = extract_sku(line.raw_description)
    if line.product_id:
        product = db.get(Product, line.product_id)
        confidence = Decimal("1")
    else:
        product, confidence = match_canonical_product(db, line.raw_description)
        if product is None:
            product = ensure_purchased_product(db, line.raw_description)
            confidence = Decimal("0.7")
    if product is None:
        return None
    pack_qty, pack_unit = parse_pack(line.raw_description, line.qty, line.unit)
    if pack_qty <= 0:
        return None
    compare_unit = compare_unit_for(product)
    unit_compare = comparable_cost(pack_price, pack_qty, pack_unit, compare_unit)
    if unit_compare is None and family(pack_unit) and family(compare_unit) != family(pack_unit):
        product.compare_unit = pack_unit
        if family(product.base_unit or "") != family(pack_unit):
            product.base_unit = pack_unit
        compare_unit = pack_unit
        unit_compare = comparable_cost(pack_price, pack_qty, pack_unit, compare_unit)
    qty_base = to_base(pack_qty, pack_unit, product.base_unit or compare_unit) or Decimal("0")
    unit_base = (pack_price / qty_base) if qty_base > 0 else Decimal("0")
    if unit_compare is None:
        return None
    existing = (
        db.query(PurchasePrice).filter(PurchasePrice.invoice_line_id == line.id).first() if line.id else None
    )
    if existing:
        existing.pack_qty = pack_qty
        existing.pack_unit = pack_unit
        existing.pack_price = pack_price
        existing.qty_base = qty_base
        existing.unit_cost_base = unit_base
        existing.compare_qty = to_base(pack_qty, pack_unit, compare_unit) or Decimal("0")
        existing.unit_cost_compare = unit_compare
        existing.raw_description = str(line.raw_description or "")[:240]
        existing.confidence = confidence
        if sku:
            existing.sku = sku
        product.current_cost = unit_base
        if supplier:
            upsert_equivalent(
                db,
                product,
                supplier,
                {
                    "sku": sku,
                    "description": line.raw_description,
                    "pack_qty": pack_qty,
                    "pack_unit": pack_unit,
                    "pack_price": pack_price,
                },
                seen_on=invoice.issued_on,
                source="invoice",
            )
        return existing
    row = PurchasePrice(
        product_id=product.id,
        supplier_id=invoice.supplier_id,
        invoice_id=invoice.id,
        invoice_line_id=line.id,
        purchased_on=invoice.issued_on,
        sku=sku,
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
    if supplier:
        upsert_equivalent(
            db,
            product,
            supplier,
            {
                "sku": sku,
                "description": line.raw_description,
                "pack_qty": pack_qty,
                "pack_unit": pack_unit,
                "pack_price": pack_price,
            },
            seen_on=invoice.issued_on,
            source="invoice",
        )
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


def latest_by_supplier(db: Session, product_id: int, source: str | None = None, days: int | None = None, sources: tuple[str, ...] | None = None) -> list[PurchasePrice]:
    query = db.query(PurchasePrice).filter(PurchasePrice.product_id == product_id)
    if sources:
        query = query.filter(PurchasePrice.source.in_(sources))
    elif source == "catalog":
        query = query.filter(PurchasePrice.source.in_(PUBLIC_SOURCES))
    elif source == "invoice":
        query = query.filter(PurchasePrice.source.in_(PAID_SOURCES))
    elif source == "account":
        query = query.filter(PurchasePrice.source.in_(ACCOUNT_SOURCES))
    elif source == "benchmark":
        query = query.filter(PurchasePrice.source.in_(BENCHMARK_SOURCES))
    if days is not None:
        query = query.filter(PurchasePrice.purchased_on >= _cutoff(days))
    rows = query.order_by(PurchasePrice.purchased_on.desc(), PurchasePrice.id.desc()).all()
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
        if row.source == "catalog":
            continue
        if row.source in PUBLIC_SOURCES or row.source in BENCHMARK_SOURCES:
            continue
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
        if row.source == "catalog":
            continue
        if row.source in PUBLIC_SOURCES or row.source in BENCHMARK_SOURCES:
            continue
        if row.purchased_on is None or row.purchased_on < cutoff:
            continue
        volumes[row.supplier_id] = volumes.get(row.supplier_id, Decimal("0")) + Decimal(str(row.compare_qty or 0))
    return volumes


def offer_miles(row: PurchasePrice) -> Decimal:
    if row.miles and Decimal(str(row.miles)) > 0:
        return Decimal(str(row.miles))
    if row.supplier is not None and row.supplier.miles:
        return Decimal(str(row.supplier.miles))
    return Decimal("0")


def classify_trip(row: PurchasePrice, gap_pct: Decimal, net: Decimal) -> str:
    miles = offer_miles(row)
    if gap_pct < GAP_PCT_THRESHOLD or net < STAY_THRESHOLD:
        return "skip"
    if row.source in BENCHMARK_SOURCES:
        return "skip"
    if miles > FAR_MILES:
        return "skip"
    if row.source in PAID_SOURCES and miles <= NEAR_MILES:
        return "go"
    return "maybe"


def vendor_short(name: str) -> str:
    label = str(name or "").strip()
    if label in VENDOR_SHORT:
        return VENDOR_SHORT[label]
    return label.split("·")[0].strip()[:16]


def product_comparison(db: Session, product: Product, days: int | None = None) -> dict | None:
    paid = latest_by_supplier(db, product.id, source="invoice", days=days)
    account = latest_by_supplier(db, product.id, source="account", days=days if days is not None else 21)
    public = latest_by_supplier(db, product.id, source="catalog", days=21)
    benchmark = latest_by_supplier(db, product.id, source="benchmark", days=400)
    if not paid and not account and not public:
        return None
    compare_unit = compare_unit_for(product)
    volumes = _volume_by_supplier(db, product.id, days=USAGE_DAYS)
    if paid:
        current = max(
            paid,
            key=lambda row: (
                volumes.get(row.supplier_id, Decimal("0")),
                row.purchased_on.toordinal() if row.purchased_on else 0,
            ),
        )
    else:
        pool = account + public
        current = min(pool, key=lambda row: Decimal(str(row.unit_cost_compare)))
    offers = paid + account + public
    cheapest = min(offers, key=lambda row: Decimal(str(row.unit_cost_compare)))
    gap = money(Decimal(str(current.unit_cost_compare)) - Decimal(str(cheapest.unit_cost_compare)))
    usage = monthly_usage_compare(db, product, days=USAGE_DAYS)
    monthly_unit = money(gap * usage) if usage else money(0)
    cheapest_supplier = cheapest.supplier
    current_supplier = current.supplier
    trip = Decimal(str(cheapest_supplier.trip_cost or 0)) if cheapest_supplier else Decimal("0")
    delivery = Decimal(str(cheapest_supplier.delivery_fee or 0)) if cheapest_supplier else Decimal("0")
    extra = trip + delivery
    if current_supplier and cheapest_supplier and cheapest_supplier.id != current_supplier.id:
        extra -= Decimal(str(current_supplier.delivery_fee or 0))
    net = money(monthly_unit - extra)
    gap_pct = cost_percent(gap, current.unit_cost_compare)
    trip_class = "skip"
    recommend = "stay"
    if cheapest.supplier_id != current.supplier_id and gap > 0:
        trip_class = classify_trip(cheapest, gap_pct, net)
        if trip_class == "go":
            recommend = "switch"
        elif trip_class == "maybe":
            recommend = "consider"
        else:
            recommend = "stay"
            net = money(0)
    if cheapest.supplier_id == current.supplier_id:
        recommend = "stay"
        trip_class = "skip"
        net = money(0)
        monthly_unit = money(0)
        gap = money(0)
        gap_pct = money(0)
    nearby = [
        row
        for row in offers
        if row.supplier_id != current.supplier_id and offer_miles(row) <= FAR_MILES
    ]
    return {
        "product": product,
        "compare_unit": compare_unit,
        "current": current,
        "cheapest": cheapest,
        "offers": sorted(offers, key=lambda row: Decimal(str(row.unit_cost_compare))),
        "paid": paid,
        "account": account,
        "market": sorted(public, key=lambda row: Decimal(str(row.unit_cost_compare))),
        "benchmark": benchmark,
        "nearby": sorted(nearby, key=lambda row: Decimal(str(row.unit_cost_compare))),
        "gap": gap,
        "gap_pct": gap_pct,
        "usage": usage,
        "monthly": monthly_unit,
        "net": net,
        "trip_cost": trip,
        "delivery_fee": delivery,
        "min_order": Decimal(str(cheapest_supplier.min_order or 0)) if cheapest_supplier else Decimal("0"),
        "miles": offer_miles(cheapest),
        "band": radius_band(offer_miles(cheapest)),
        "trip_class": trip_class,
        "recommend": recommend,
        "market_label": HOME_MARKET,
        "impacts": recipe_impacts(
            db,
            product,
            Decimal(str(current.unit_cost_compare)),
            Decimal(str(cheapest.unit_cost_compare)),
        ),
        "equivalents": _equivalent_rows(db, product, offers),
        "cells": _cells_by_supplier(offers),
    }


def _equivalent_rows(db: Session, product: Product, offers: list[PurchasePrice]) -> list[dict]:
    from app.equivalents import equivalents_for

    offer_by_supplier = {}
    for row in offers:
        current = offer_by_supplier.get(row.supplier_id)
        if current is None or Decimal(str(row.unit_cost_compare)) < Decimal(str(current.unit_cost_compare)):
            offer_by_supplier[row.supplier_id] = row
    rows = []
    for equivalent in equivalents_for(db, product):
        offer = offer_by_supplier.get(equivalent.supplier_id)
        unit_cost = Decimal(str(offer.unit_cost_compare)) if offer else Decimal("0")
        rows.append(
            {
                "supplier": equivalent.supplier.name if equivalent.supplier else "",
                "sku": equivalent.sku,
                "pack": f"{equivalent.pack_qty} {equivalent.pack_unit}".strip(),
                "unit_cost": unit_cost,
                "last_price": Decimal(str(equivalent.last_price or 0)),
                "last_seen": equivalent.last_seen,
                "source": equivalent.source,
            }
        )
    rows.sort(key=lambda item: (item["unit_cost"] == 0, item["unit_cost"], item["supplier"]))
    return rows


def _cells_by_supplier(offers: list[PurchasePrice]) -> dict[int, PurchasePrice]:
    cells: dict[int, PurchasePrice] = {}
    for row in offers:
        if not row.supplier_id or row.source in BENCHMARK_SOURCES:
            continue
        current = cells.get(row.supplier_id)
        if current is None or Decimal(str(row.unit_cost_compare)) < Decimal(str(current.unit_cost_compare)):
            cells[row.supplier_id] = row
    return cells


def matrix_vendors(cards: list[dict]) -> list[Supplier]:
    found: dict[int, Supplier] = {}
    for card in cards:
        for row in (card.get("cells") or {}).values():
            if row.supplier:
                found[row.supplier.id] = row.supplier
    def rank(supplier: Supplier) -> tuple:
        name = supplier.name
        try:
            return (0, VENDOR_ORDER.index(name), name.lower())
        except ValueError:
            return (1, 99, name.lower())
    return sorted(found.values(), key=rank)[:10]


def seasonal_hint(db: Session, product: Product, card: dict) -> str:
    cutoff = _cutoff(365)
    rows = (
        db.query(PurchasePrice)
        .filter(
            PurchasePrice.product_id == product.id,
            PurchasePrice.source.in_(PAID_SOURCES + ACCOUNT_SOURCES),
            PurchasePrice.purchased_on >= cutoff,
        )
        .all()
    )
    unit = card["compare_unit"]
    current_name = card["current"].supplier.name if card["current"].supplier else "your usual"
    cheapest_name = card["cheapest"].supplier.name if card["cheapest"].supplier else "another vendor"
    if rows:
        best = min(rows, key=lambda row: Decimal(str(row.unit_cost_compare)))
        period_cost = Decimal(str(card["cheapest"].unit_cost_compare))
        best_cost = Decimal(str(best.unit_cost_compare))
        if best.supplier and best_cost + Decimal("0.02") < period_cost and best.purchased_on:
            when = best.purchased_on.strftime("%b %Y")
            return f"In {when} it was cheaper at {best.supplier.name} ({money(best_cost)}/{unit})."
    if card["recommend"] in ("switch", "consider"):
        return f"This window: {cheapest_name} is {card['gap_pct']}% under {current_name}."
    if card["current"].supplier:
        return f"Stay with {current_name}."
    return ""


def purchasing_board(db: Session, category: str = "", days: int | None = DEFAULT_COMPARE_DAYS) -> dict:
    query = db.query(Product).filter(Product.is_active.is_(True))
    if category:
        query = query.filter(
            (Product.purchasing_category == category) | (Product.category == category)
        )
    cards = []
    monthly_total = Decimal("0")
    cheaper_elsewhere = 0
    window = days if days in COMPARE_DAYS or days is None else DEFAULT_COMPARE_DAYS
    for product in query.order_by(Product.name).all():
        card = product_comparison(db, product, days=window)
        if not card:
            continue
        card["hint"] = seasonal_hint(db, product, card)
        cards.append(card)
        monthly_total += Decimal(str(card["net"] if card["recommend"] in ("switch", "consider") else 0))
        if card["recommend"] in ("switch", "consider"):
            cheaper_elsewhere += 1
    cards.sort(key=lambda item: item["product"].name.lower())
    vendors = matrix_vendors(cards)
    tips = [card for card in cards if card["recommend"] in ("switch", "consider")][:5]
    return {
        "cards": cards,
        "vendors": vendors,
        "tips": tips,
        "monthly_total": money(monthly_total),
        "cheaper_elsewhere": cheaper_elsewhere,
        "category": category,
        "days": window or DEFAULT_COMPARE_DAYS,
        "stay_threshold": STAY_THRESHOLD,
        "gap_pct_threshold": GAP_PCT_THRESHOLD,
        "market": HOME_MARKET,
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
                "hint": card.get("hint") or "",
                "trip_class": card.get("trip_class") or "skip",
                "miles": float(card.get("miles") or 0),
                "best_source": card["cheapest"].source,
                "equivalents": [
                    {
                        "supplier": item["supplier"],
                        "sku": item["sku"],
                        "pack": item["pack"],
                        "unit_cost": float(item["unit_cost"] or 0),
                        "last_price": float(item["last_price"] or 0),
                        "last_seen": item["last_seen"].isoformat() if item["last_seen"] else None,
                        "source": item["source"],
                    }
                    for item in card.get("equivalents") or []
                ],
                "offers": [
                    {
                        "supplier": row.supplier.name if row.supplier else "",
                        "pack": f"{row.pack_qty} {row.pack_unit}",
                        "pack_price": float(row.pack_price),
                        "unit_cost": float(row.unit_cost_compare),
                        "purchased_on": row.purchased_on.isoformat() if row.purchased_on else None,
                        "source": row.source,
                        "miles": float(offer_miles(row)),
                        "confidence": float(row.confidence or 0),
                        "kind": row.source,
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
        "days": board.get("days") or DEFAULT_COMPARE_DAYS,
        "vendors": [row.name for row in board.get("vendors") or []],
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
            exists.exclude = exclude
            continue
        db.add(ProductAlias(product_id=product.id, alias=alias, exclude=exclude))
    for name, spec in LOCAL_SUPPLIERS.items():
        supplier = db.query(Supplier).filter(Supplier.name == name).first()
        if supplier is None:
            continue
        if not supplier.city:
            supplier.city = spec["city"]
        if not supplier.miles:
            supplier.miles = spec["miles"]
    db.commit()
