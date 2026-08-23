"""Physical shelf counts. Empty means skipped. Zero means you counted zero."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.costing import money
from app.models import InventoryCount, InventoryCountLine, Product, PurchasePrice, StockMove
from app.services import on_hand_base

COUNT_LOCATIONS = (
    ("walk-in", "Walk-in cooler", ("dairy", "produce", "meat")),
    ("prep", "Prep cooler", ("dairy", "produce", "food")),
    ("line", "Line cooler", ("dairy", "food")),
    ("pastry", "Pastry cooler", ("dairy", "food")),
    ("bar", "Bar", ("beverage", "beer")),
    ("wine-cellar", "Wine cellar", ("wine",)),
    ("freezer", "Walk-in freezer", ("meat",)),
    ("dry", "Dry storage", ("food", "cleaning")),
)

LOCATION_LABELS = {slug: label for slug, label, _cats in COUNT_LOCATIONS}

TO_BASE = {
    ("g", "lb"): Decimal("453.592"),
    ("g", "oz"): Decimal("28.3495"),
    ("g", "kg"): Decimal("1000"),
    ("ml", "gal"): Decimal("3785.41"),
    ("ml", "qt"): Decimal("946.353"),
    ("ml", "l"): Decimal("1000"),
    ("ml", "floz"): Decimal("29.5735"),
}


def _dec(value) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if text == "":
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def default_location(product: Product) -> str:
    if product.wine or product.category == "wine" or product.purchasing_category == "wine":
        return "wine-cellar"
    group = product.purchasing_category or product.category
    for slug, _label, cats in COUNT_LOCATIONS:
        if group in cats:
            return slug
    return "dry"


def last_purchase(db: Session, product_id: int) -> PurchasePrice | None:
    return (
        db.query(PurchasePrice)
        .filter(PurchasePrice.product_id == product_id)
        .order_by(PurchasePrice.purchased_on.desc(), PurchasePrice.id.desc())
        .first()
    )


def last_count_line(db: Session, product_id: int) -> InventoryCountLine | None:
    return (
        db.query(InventoryCountLine)
        .join(InventoryCount)
        .filter(InventoryCountLine.product_id == product_id)
        .order_by(InventoryCount.counted_at.desc(), InventoryCountLine.id.desc())
        .first()
    )


def count_spec(db: Session, product: Product) -> dict:
    if product.wine:
        size = Decimal(product.wine.bottle_size_ml or 750)
        return {"unit": "bottle", "factor": size, "base": "ml", "par": Decimal(product.wine.par_bottles or 0)}
    last = last_purchase(db, product.id)
    if last and last.pack_qty and last.qty_base and last.pack_unit:
        factor = Decimal(last.qty_base) / Decimal(last.pack_qty)
        if factor > 0:
            return {"unit": last.pack_unit, "factor": factor, "base": product.base_unit or "each", "par": Decimal(0)}
    unit = (product.compare_unit or product.base_unit or "each").lower()
    base = (product.base_unit or "each").lower()
    factor = TO_BASE.get((base, unit), Decimal(1))
    return {"unit": unit, "factor": factor, "base": base, "par": Decimal(0)}


def to_count_qty(qty_base: Decimal, spec: dict) -> Decimal:
    factor = spec["factor"] or Decimal(1)
    if factor == 0:
        return Decimal(0)
    return (Decimal(qty_base or 0) / factor).quantize(Decimal("0.01"))


def to_base_qty(counted: Decimal, spec: dict) -> Decimal:
    return (Decimal(counted) * spec["factor"]).quantize(Decimal("0.0001"))


def count_sheet(db: Session, location: str, q: str = "") -> dict:
    slug = location if location in LOCATION_LABELS else "walk-in"
    needle = q.strip().lower()
    products = (
        db.query(Product)
        .options(joinedload(Product.wine))
        .filter(Product.is_active.is_(True))
        .order_by(Product.name)
        .all()
    )
    rows = []
    for product in products:
        home = default_location(product)
        name = product.name.lower()
        if needle:
            if needle not in name and needle not in (product.sku or "").lower():
                continue
        elif home != slug:
            continue
        spec = count_spec(db, product)
        on_hand = on_hand_base(db, product.id)
        last = last_count_line(db, product.id)
        counted_before = last is not None
        book = to_count_qty(on_hand, spec) if counted_before else None
        last_qty = to_count_qty(last.counted_qty_base, spec) if last else None
        rows.append(
            {
                "product": product,
                "spec": spec,
                "location": home,
                "book": book,
                "last": last_qty,
                "counted_before": counted_before,
                "par": spec["par"],
            }
        )
    latest = (
        db.query(InventoryCount)
        .filter(InventoryCount.location == slug)
        .order_by(InventoryCount.counted_at.desc())
        .first()
    )
    return {
        "location": slug,
        "label": LOCATION_LABELS[slug],
        "rows": rows,
        "last_count": latest,
        "q": q.strip(),
    }


def save_count(db: Session, location: str, raw_qty: dict[int, str], notes: str = "") -> dict:
    slug = location if location in LOCATION_LABELS else "walk-in"
    count = InventoryCount(
        counted_at=datetime.now(UTC).replace(tzinfo=None),
        location=slug,
        notes=notes or "Shelf count",
    )
    db.add(count)
    db.flush()
    saved = 0
    for product_id, raw in raw_qty.items():
        counted = _dec(raw)
        if counted is None:
            continue
        product = db.get(Product, product_id)
        if product is None:
            continue
        spec = count_spec(db, product)
        qty_base = to_base_qty(counted, spec)
        expected = on_hand_base(db, product.id)
        db.add(
            InventoryCountLine(
                count_id=count.id,
                product_id=product.id,
                counted_qty_base=qty_base,
                expected_qty_base=expected,
            )
        )
        delta = qty_base - expected
        if delta != 0:
            db.add(
                StockMove(
                    product_id=product.id,
                    qty_base=delta,
                    unit_cost=money(product.current_cost or 0),
                    reason="count_adjust",
                    location=slug,
                    notes=f"Counted {counted} {spec['unit']}",
                )
            )
        saved += 1
    if saved == 0:
        db.delete(count)
        db.commit()
        return {"ok": False, "saved": 0, "count_id": None}
    db.commit()
    return {"ok": True, "saved": saved, "count_id": count.id, "location": slug}


def recent_counts(db: Session, limit: int = 12) -> list[InventoryCount]:
    return db.query(InventoryCount).order_by(InventoryCount.counted_at.desc()).limit(limit).all()


def count_detail(db: Session, count_id: int) -> dict | None:
    row = (
        db.query(InventoryCount)
        .options(joinedload(InventoryCount.lines).joinedload(InventoryCountLine.product))
        .filter(InventoryCount.id == count_id)
        .first()
    )
    if row is None:
        return None
    lines = []
    for line in row.lines:
        spec = count_spec(db, line.product)
        counted = to_count_qty(line.counted_qty_base, spec)
        expected = to_count_qty(line.expected_qty_base, spec)
        lines.append(
            {
                "product": line.product,
                "unit": spec["unit"],
                "counted": counted,
                "expected": expected,
                "variance": counted - expected,
            }
        )
    lines.sort(key=lambda item: item["product"].name)
    return {"count": row, "label": LOCATION_LABELS.get(row.location, row.location), "lines": lines}


def last_count_at(db: Session) -> datetime | None:
    return db.scalar(select(func.max(InventoryCount.counted_at)))
