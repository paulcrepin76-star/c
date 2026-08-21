from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from app.costing import cost_percent, money
from app.geo import FAR_MILES, HOME_MARKET, LOCAL_SUPPLIERS, MID_MILES, NEAR_MILES, radius_band
from app.models import CollectorRun, Connection, Invoice, InvoiceLine, Product, ProductAlias, PurchasePrice, Recipe, RecipeLine, Supplier
from app.names import looks_like_vendor_noise, pretty_item
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
FRESH_DAYS = 7
OK_DAYS = 30
STALE_DAYS = 90
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
SCAN_VENDORS = (
    ("chefs-warehouse", "Chef's Warehouse"),
    ("gordon", "Gordon Food Service"),
    ("sams-club", "Sam's Club"),
    ("costco", "Costco"),
    ("restaurant-depot", "Restaurant Depot"),
    ("webstaurantstore", "WebstaurantStore"),
    ("publix", "Publix"),
)

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
    pretty, _pack = pretty_item(text)
    food = (pretty or food)[:80].strip(" -")
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


def offer_age_days(row: PurchasePrice, today: date | None = None) -> int | None:
    if not row.purchased_on:
        return None
    return ((today or date.today()) - row.purchased_on).days


def freshness_band(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= FRESH_DAYS:
        return "fresh"
    if days <= OK_DAYS:
        return "ok"
    if days <= STALE_DAYS:
        return "stale"
    return "old"


def age_label(days: int | None) -> str:
    if days is None:
        return ""
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 45:
        weeks = max(1, days // 7)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = max(1, days // 30)
    if months >= 6:
        return f"{months} months old"
    return f"{months} month{'s' if months != 1 else ''} old"


def is_fresh_enough(row: PurchasePrice) -> bool:
    return freshness_band(offer_age_days(row)) != "old"


def fulfillment_for(row: PurchasePrice) -> str:
    miles = offer_miles(row)
    city = (row.supplier.city if row.supplier else "") or ""
    if city in {"delivered", "online"} or miles <= 0:
        return "Delivered"
    return f"Pickup · {miles} mi"


def sparkline_svg(values: list[Decimal | float], width: int = 84, height: int = 22) -> str:
    nums = [float(v) for v in values if v is not None]
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    pts = []
    for index, value in enumerate(nums):
        x = index * (width / (len(nums) - 1))
        y = height - 3 - ((value - lo) / span) * (height - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    color = "#1a7a72" if nums[-1] <= nums[0] else "#b42318"
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{" ".join(pts)}"/></svg>'
    )


def _display_for(product: Product, row: PurchasePrice | None = None) -> tuple[str, str]:
    pretty, pack = pretty_item(product.name)
    if row and (not pretty or not pack):
        alt, alt_pack = pretty_item(row.raw_description or "", row.pack_qty, row.pack_unit)
        pretty = pretty or alt
        pack = pack or alt_pack
    if not pack and row and row.pack_qty and row.pack_unit:
        pack = f"{row.pack_qty} {row.pack_unit}".replace(".0000", "").strip()
    return pretty or product.name, pack


def _price_change(db: Session, product_id: int, supplier_id: int | None, days: int = 60) -> dict:
    empty = {"pct": Decimal("0"), "old": None, "new": None, "spark": "", "points": []}
    if not supplier_id:
        return empty
    rows = (
        db.query(PurchasePrice)
        .filter(
            PurchasePrice.product_id == product_id,
            PurchasePrice.supplier_id == supplier_id,
            PurchasePrice.source.in_(PAID_SOURCES + ACCOUNT_SOURCES),
            PurchasePrice.purchased_on >= _cutoff(days),
        )
        .order_by(PurchasePrice.purchased_on.asc(), PurchasePrice.id.asc())
        .all()
    )
    points = [Decimal(str(row.unit_cost_compare)) for row in rows]
    if len(points) < 2:
        return {**empty, "points": points, "spark": sparkline_svg(points)}
    old, new = points[0], points[-1]
    pct = money(((new - old) / old) * 100) if old > 0 else Decimal("0")
    return {"pct": pct, "old": old, "new": new, "spark": sparkline_svg(points), "points": points}


def _action_badge(recommend: str, usable: list[PurchasePrice], current: PurchasePrice, cheapest: PurchasePrice, net, gap) -> dict:
    suppliers = {row.supplier_id for row in usable}
    best_name = vendor_short(cheapest.supplier.name) if cheapest.supplier else "another vendor"
    current_name = vendor_short(current.supplier.name) if current.supplier else "current"
    if cheapest.is_discounted and cheapest.supplier_id != current.supplier_id:
        return {
            "code": "promo",
            "label": "Promo",
            "detail": f"{best_name} has a discounted pack.",
        }
    if len(suppliers) < 2:
        return {
            "code": "none",
            "label": "No comparison",
            "detail": "Only one vendor has a price fresh enough to trust.",
        }
    if recommend == "switch":
        return {
            "code": "switch",
            "label": "Switch",
            "detail": f"{best_name} · save {money(net)}/mo",
        }
    if recommend == "consider":
        return {
            "code": "watch",
            "label": "Watch",
            "detail": f"Consider {best_name} · {money(net)}/mo after the trip",
        }
    if Decimal(str(gap or 0)) > 0:
        return {
            "code": "stay",
            "label": "Stay",
            "detail": f"Don't switch — saving is below {money(STAY_THRESHOLD)}/mo or {GAP_PCT_THRESHOLD}% after the trip.",
        }
    return {"code": "stay", "label": "Stay", "detail": f"Stay with {current_name}."}


def _vendor_rows(offers: list[PurchasePrice], current: PurchasePrice, cheapest: PurchasePrice) -> list[dict]:
    rows = []
    for offer in sorted(offers, key=lambda row: Decimal(str(row.unit_cost_compare))):
        age = offer_age_days(offer)
        rows.append(
            {
                "supplier": offer.supplier.name if offer.supplier else "",
                "short": vendor_short(offer.supplier.name if offer.supplier else ""),
                "unit_cost": offer.unit_cost_compare,
                "is_current": offer.id == current.id,
                "is_best": offer.id == cheapest.id,
                "age_days": age,
                "freshness": freshness_band(age),
                "age_label": age_label(age),
                "pack": f"{offer.pack_qty} {offer.pack_unit}".replace(".0000", "").strip(),
                "raw": offer.raw_description or "",
                "fulfillment": fulfillment_for(offer),
                "source": offer.source,
                "min_order": Decimal(str(offer.supplier.min_order or 0)) if offer.supplier else Decimal("0"),
                "delivery_fee": Decimal(str(offer.supplier.delivery_fee or 0)) if offer.supplier else Decimal("0"),
                "miles": offer_miles(offer),
            }
        )
    return rows


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
    usable = [row for row in offers if is_fresh_enough(row)]
    rec_pool = usable or [current]
    cheapest = min(rec_pool, key=lambda row: Decimal(str(row.unit_cost_compare)))
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
    same_vendor = cheapest.supplier_id == current.supplier_id
    if not same_vendor and gap > 0:
        trip_class = classify_trip(cheapest, gap_pct, net)
        cheapest_band = freshness_band(offer_age_days(cheapest))
        if trip_class == "go" and cheapest_band == "stale":
            recommend = "consider"
        elif trip_class == "go":
            recommend = "switch"
        elif trip_class == "maybe":
            recommend = "consider"
        else:
            recommend = "stay"
    if same_vendor:
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
    display_name, pack_label = _display_for(product, current)
    change = _price_change(db, product.id, current.supplier_id)
    badge = _action_badge(recommend, usable or offers, current, cheapest, net, gap)
    return {
        "product": product,
        "display_name": display_name,
        "pack_label": pack_label,
        "compare_unit": compare_unit,
        "current": current,
        "cheapest": cheapest,
        "offers": sorted(offers, key=lambda row: Decimal(str(row.unit_cost_compare))),
        "vendor_rows": _vendor_rows(offers, current, cheapest),
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
        "badge": badge,
        "change_pct": change["pct"],
        "previous_cost": change["old"],
        "spark": change["spark"],
        "current_fulfillment": fulfillment_for(current),
        "best_fulfillment": fulfillment_for(cheapest),
        "current_age": age_label(offer_age_days(current)),
        "best_age": age_label(offer_age_days(cheapest)),
        "current_freshness": freshness_band(offer_age_days(current)),
        "best_freshness": freshness_band(offer_age_days(cheapest)),
        "compared": len({row.supplier_id for row in usable}) >= 2,
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


def purchasing_board(db: Session, category: str = "", days: int | None = DEFAULT_COMPARE_DAYS, view: str = "") -> dict:
    query = db.query(Product).filter(Product.is_active.is_(True))
    if category:
        query = query.filter(
            (Product.purchasing_category == category) | (Product.category == category)
        )
    products = query.order_by(Product.name).all()
    total_products = len(products)
    canonical_skus = {spec["sku"] for spec in CANONICAL_PRODUCTS}
    cards = []
    monthly_total = Decimal("0")
    cheaper_elsewhere = 0
    compared = 0
    increases = 0
    promos = 0
    window = days if days in COMPARE_DAYS or days is None else DEFAULT_COMPARE_DAYS
    for product in products:
        card = product_comparison(db, product, days=window)
        if not card:
            continue
        if product.sku not in canonical_skus:
            if looks_like_vendor_noise(card["display_name"]) or not pretty_item(card["display_name"])[0]:
                continue
        card["hint"] = seasonal_hint(db, product, card)
        cards.append(card)
        if card.get("compared"):
            compared += 1
        if Decimal(str(card.get("change_pct") or 0)) >= GAP_PCT_THRESHOLD:
            increases += 1
        if (card.get("badge") or {}).get("code") == "promo" or any(row.is_discounted for row in card["offers"]):
            promos += 1
        monthly_total += Decimal(str(card["net"] if card["recommend"] in ("switch", "consider") else 0))
        if card["recommend"] in ("switch", "consider"):
            cheaper_elsewhere += 1
    if view == "opportunities":
        cards = [
            card
            for card in cards
            if card["recommend"] in ("switch", "consider")
            or Decimal(str(card.get("change_pct") or 0)) >= GAP_PCT_THRESHOLD
            or (card.get("badge") or {}).get("code") == "promo"
        ]
    cards.sort(
        key=lambda item: (
            {"switch": 0, "consider": 1}.get(item["recommend"], 2),
            -float(item["net"] or 0),
            -float(item.get("change_pct") or 0),
            str(item.get("display_name") or item["product"].name).lower(),
        )
    )
    vendors = matrix_vendors(cards)
    tips = [card for card in cards if card["recommend"] in ("switch", "consider")][:5]
    increases_list = [
        card for card in cards if Decimal(str(card.get("change_pct") or 0)) >= GAP_PCT_THRESHOLD
    ][:5]
    scan = vendor_scan_status(db)
    return {
        "cards": cards,
        "vendors": vendors,
        "tips": tips,
        "increases": increases_list,
        "monthly_total": money(monthly_total),
        "cheaper_elsewhere": cheaper_elsewhere,
        "worth_switching": sum(1 for card in cards if card["recommend"] == "switch"),
        "price_increases": increases,
        "promos": promos,
        "compared": compared,
        "total_products": total_products,
        "scan": scan,
        "category": category,
        "days": window or DEFAULT_COMPARE_DAYS,
        "view": view,
        "stay_threshold": STAY_THRESHOLD,
        "gap_pct_threshold": GAP_PCT_THRESHOLD,
        "market": HOME_MARKET,
    }


def vendor_scan_status(db: Session) -> dict:
    from app.connections import extra_dict

    run = db.query(CollectorRun).order_by(CollectorRun.id.desc()).first()
    latest_by_name: dict[str, tuple[date | None, int]] = {}
    cutoff = _cutoff(30)
    rows = db.query(PurchasePrice).filter(PurchasePrice.purchased_on >= cutoff).all()
    for row in rows:
        if not row.supplier:
            continue
        name = row.supplier.name
        seen_on, count = latest_by_name.get(name, (None, 0))
        purchased = row.purchased_on
        if seen_on is None or (purchased and purchased > seen_on):
            seen_on = purchased
        latest_by_name[name] = (seen_on, count + 1)
    vendors = []
    last_times: list[datetime] = []
    if run and run.finished_at:
        last_times.append(run.finished_at)
    for slug, label in SCAN_VENDORS:
        row = db.query(Connection).filter(Connection.name == slug).first()
        extra = extra_dict(row) if row else {}
        browser_status = str(extra.get("browser_status") or "")
        seen_on, count = latest_by_name.get(label, (None, 0))
        status = "ok"
        note = ""
        if browser_status == "needs_reauth":
            status = "warn"
            note = "Login expired"
        elif not seen_on and browser_status in ("never_logged_in", ""):
            status = "idle"
            note = "No recent prices"
        success = str(extra.get("browser_success_at") or "")
        scanned = None
        if success:
            try:
                scanned = datetime.fromisoformat(success.replace("Z", ""))
                last_times.append(scanned)
            except ValueError:
                scanned = None
        vendors.append(
            {
                "slug": slug,
                "label": label,
                "short": vendor_short(label),
                "status": status,
                "note": note,
                "count": count,
                "seen_on": seen_on,
                "scanned_at": scanned,
            }
        )
    last_scan = max(last_times) if last_times else None
    if last_scan is None:
        dates = [seen for seen, _count in latest_by_name.values() if seen]
        if dates:
            last_scan = datetime.combine(max(dates), datetime.min.time())
    updated = int(run.updated) if run else sum(item["count"] for item in vendors)
    return {
        "last_scan": last_scan,
        "last_scan_label": last_scan.strftime("%I:%M %p").lstrip("0") if last_scan else "No scan yet",
        "updated": updated,
        "vendors": vendors,
        "needs_reauth": [part for part in (run.needs_reauth.split(",") if run else []) if part],
    }


def polish_product_names(db: Session) -> int:
    canonical = {spec["sku"] for spec in CANONICAL_PRODUCTS}
    updated = 0
    for product in db.query(Product).filter(Product.is_active.is_(True)).all():
        if product.sku in canonical:
            continue
        pretty, _pack = pretty_item(product.name)
        if not pretty or pretty == product.name:
            continue
        clash = (
            db.query(Product)
            .filter(Product.id != product.id, Product.name.ilike(pretty))
            .first()
        )
        if clash:
            continue
        product.name = pretty[:200]
        updated += 1
    if updated:
        db.commit()
    return updated


def board_payload(board: dict) -> dict:
    cards = []
    for card in board["cards"]:
        cards.append(
            {
                "product": card.get("display_name") or card["product"].name,
                "raw_name": card["product"].name,
                "pack": card.get("pack_label") or "",
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
                "badge": (card.get("badge") or {}).get("code") or card["recommend"],
                "hint": card.get("hint") or "",
                "change_pct": float(card.get("change_pct") or 0),
                "compared": bool(card.get("compared")),
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
        "worth_switching": board.get("worth_switching") or 0,
        "price_increases": board.get("price_increases") or 0,
        "promos": board.get("promos") or 0,
        "compared": board.get("compared") or 0,
        "total_products": board.get("total_products") or 0,
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
    polish_product_names(db)
    db.commit()
