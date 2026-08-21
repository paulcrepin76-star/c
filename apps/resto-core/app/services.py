from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.costing import coefficient, cost_per_pour, cost_percent, money, recipe_cost
from app.models import Invoice, Product, Recipe, Sale, SellableItem, StockMove, Supplier, WineProfile


def on_hand_base(db: Session, product_id: int) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(StockMove.qty_base), 0)).where(StockMove.product_id == product_id))
    return Decimal(total or 0)


def wine_rows(db: Session) -> list[dict]:
    wines = (
        db.execute(
            select(Product)
            .options(joinedload(Product.wine), joinedload(Product.sellables))
            .join(WineProfile, WineProfile.product_id == Product.id)
            .where(Product.category == "wine")
            .order_by(WineProfile.color, Product.name)
        )
        .unique()
        .scalars()
        .all()
    )
    rows = []
    for product in wines:
        profile = product.wine
        if not profile:
            continue
        on_hand_ml = on_hand_base(db, product.id)
        bottles = (on_hand_ml / Decimal(profile.bottle_size_ml)) if profile.bottle_size_ml else Decimal(0)
        bottle_cost = money(product.current_cost * profile.bottle_size_ml)
        glass_item = next((s for s in product.sellables if s.serving_unit == "ml" and s.serving_qty == profile.glass_pour_ml), None)
        bottle_item = next((s for s in product.sellables if s.serving_qty == profile.bottle_size_ml), None)
        if glass_item is None:
            glass_item = next((s for s in product.sellables if "glass" in s.name.lower()), None)
        if bottle_item is None:
            bottle_item = next((s for s in product.sellables if "bottle" in s.name.lower()), None)
        glass_cost = cost_per_pour(bottle_cost, profile.bottle_size_ml, profile.glass_pour_ml) if profile.glass_pour_ml else Decimal(0)
        glass_price = glass_item.selling_price if glass_item else Decimal(0)
        bottle_price = bottle_item.selling_price if bottle_item else Decimal(0)
        rows.append(
            {
                "product": product,
                "profile": profile,
                "on_hand_ml": on_hand_ml,
                "on_hand_bottles": bottles,
                "cellar_value": money(bottles * bottle_cost),
                "bottle_cost": bottle_cost,
                "glass_cost": glass_cost,
                "glass_price": glass_price,
                "bottle_price": bottle_price,
                "glass_cost_pct": cost_percent(glass_cost, glass_price) if glass_price else Decimal(0),
                "bottle_cost_pct": cost_percent(bottle_cost, bottle_price) if bottle_price else Decimal(0),
                "below_par": bottles < Decimal(profile.par_bottles or 0),
                "glass_item": glass_item,
                "bottle_item": bottle_item,
            }
        )
    return rows


def sellable_unit_cost(db: Session, item: SellableItem) -> Decimal:
    if item.recipe_id:
        recipe = db.get(Recipe, item.recipe_id)
        if not recipe:
            return Decimal(0)
        lines = []
        for line in recipe.lines:
            lines.append((line.qty, line.product.current_cost))
        return recipe_cost(lines)
    if item.product_id:
        product = db.get(Product, item.product_id)
        if not product:
            return Decimal(0)
        return money(Decimal(item.serving_qty) * product.current_cost)
    return Decimal(0)


def period_costing(db: Session, start: datetime, end: datetime) -> dict:
    sales = (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.sellable).joinedload(SellableItem.product), joinedload(Sale.sellable).joinedload(SellableItem.recipe))
            .where(Sale.sold_at >= start, Sale.sold_at < end)
        )
        .unique()
        .scalars()
        .all()
    )
    groups = {
        "food": {"sales": Decimal(0), "cost": Decimal(0)},
        "wine": {"sales": Decimal(0), "cost": Decimal(0)},
        "beer": {"sales": Decimal(0), "cost": Decimal(0)},
        "beverage": {"sales": Decimal(0), "cost": Decimal(0)},
        "other": {"sales": Decimal(0), "cost": Decimal(0)},
    }
    wine_usage: dict[int, dict] = {}
    for sale in sales:
        item = sale.sellable
        group = item.costing_group if item.costing_group in groups else "other"
        unit_cost = sellable_unit_cost(db, item)
        groups[group]["sales"] += Decimal(sale.revenue)
        groups[group]["cost"] += unit_cost * Decimal(sale.qty)
        if item.product and item.product.category == "wine":
            usage = wine_usage.setdefault(
                item.product_id,
                {"name": item.product.name, "ml": Decimal(0), "sales": Decimal(0), "cost": Decimal(0)},
            )
            usage["ml"] += Decimal(item.serving_qty) * Decimal(sale.qty)
            usage["sales"] += Decimal(sale.revenue)
            usage["cost"] += unit_cost * Decimal(sale.qty)

    summary = {}
    for key, bucket in groups.items():
        sales_total = money(bucket["sales"])
        cost_total = money(bucket["cost"])
        summary[key] = {
            "sales": sales_total,
            "cost": cost_total,
            "cost_pct": cost_percent(cost_total, sales_total),
            "coefficient": coefficient(sales_total, cost_total) if cost_total else Decimal(0),
            "margin": money(sales_total - cost_total),
        }
    wine_details = []
    for product_id, usage in wine_usage.items():
        product = db.get(Product, product_id)
        bottle_ml = product.wine.bottle_size_ml if product and product.wine else 750
        wine_details.append(
            {
                **usage,
                "bottles": (usage["ml"] / Decimal(bottle_ml)) if bottle_ml else Decimal(0),
                "cost_pct": cost_percent(usage["cost"], usage["sales"]),
            }
        )
    wine_details.sort(key=lambda row: row["sales"], reverse=True)
    period_sales = money(sum((bucket["sales"] for bucket in summary.values()), Decimal(0)))
    return {"groups": summary, "wines": wine_details, "period_sales": period_sales}


def sales_span(db: Session) -> dict:
    last = db.scalar(select(func.max(Sale.sold_at)))
    first = db.scalar(select(func.min(Sale.sold_at)))
    all_time = db.scalar(select(func.coalesce(func.sum(Sale.revenue), 0)))
    tickets = db.scalar(select(func.count(Sale.id)))
    return {
        "first": first,
        "last": last,
        "all_time_sales": money(all_time or 0),
        "tickets": int(tickets or 0),
    }


def _iso_day(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def _num(value) -> float:
    return float(money(value or 0))


def daily_activity(db: Session, start: datetime, end: datetime) -> dict:
    """Sales vs invoice spend by day, plus vendor mix for the dashboard charts."""
    sales_map: dict[str, float] = {}
    for sold_at, revenue in db.execute(
        select(Sale.sold_at, Sale.revenue).where(Sale.sold_at >= start, Sale.sold_at < end)
    ):
        if not sold_at:
            continue
        key = _iso_day(sold_at)
        sales_map[key] = round(sales_map.get(key, 0.0) + _num(revenue), 2)
    invoice_rows = db.execute(
        select(Invoice.issued_on, func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.issued_on.is_not(None), Invoice.issued_on >= start.date(), Invoice.issued_on <= end.date())
        .group_by(Invoice.issued_on)
    ).all()
    vendor_name = func.coalesce(Supplier.name, "Unknown")
    vendor_rows = db.execute(
        select(vendor_name, func.coalesce(func.sum(Invoice.total), 0))
        .select_from(Invoice)
        .outerjoin(Supplier, Supplier.id == Invoice.supplier_id)
        .where(Invoice.issued_on.is_not(None), Invoice.issued_on >= start.date(), Invoice.issued_on <= end.date())
        .group_by(vendor_name)
        .order_by(func.coalesce(func.sum(Invoice.total), 0).desc())
        .limit(8)
    ).all()
    invoice_map = {_iso_day(day): _num(total) for day, total in invoice_rows if day}
    cursor = start.date()
    last = end.date()
    labels: list[str] = []
    sales: list[float] = []
    purchases: list[float] = []
    while cursor <= last:
        key = cursor.isoformat()
        labels.append(key)
        sales.append(sales_map.get(key, 0.0))
        purchases.append(invoice_map.get(key, 0.0))
        cursor += timedelta(days=1)
    invoice_spend = money(sum(invoice_map.values(), 0.0))
    return {
        "labels": labels,
        "sales": sales,
        "purchases": purchases,
        "invoice_spend": invoice_spend,
        "vendors": [{"name": str(name), "spend": _num(total)} for name, total in vendor_rows],
    }


def dashboard_charts(costing: dict, activity: dict) -> dict:
    groups = costing["groups"]
    mix = []
    cost_bars = []
    for key in ("food", "wine", "beverage", "beer", "other"):
        bucket = groups[key]
        if bucket["sales"] or bucket["cost"]:
            mix.append({"name": key, "sales": _num(bucket["sales"])})
            cost_bars.append({"name": key, "pct": _num(bucket["cost_pct"]), "cost": _num(bucket["cost"])})
    theoretical_cost = money(sum((groups[key]["cost"] for key in groups), Decimal(0)))
    period_sales = costing["period_sales"]
    return {
        "labels": activity["labels"],
        "sales": activity["sales"],
        "purchases": activity["purchases"],
        "mix": mix,
        "cost_bars": cost_bars,
        "vendors": activity["vendors"],
        "theoretical_cost": _num(theoretical_cost),
        "theoretical_pct": _num(cost_percent(theoretical_cost, period_sales)),
        "invoice_spend": _num(activity["invoice_spend"]),
        "purchase_pct": _num(cost_percent(activity["invoice_spend"], period_sales)),
        "margin": _num(money(period_sales - theoretical_cost)),
    }


def catalog_counts(db: Session) -> dict:
    recipes = db.scalar(select(func.count(Recipe.id))) or 0
    invoices = db.scalar(select(func.count(Invoice.id))) or 0
    invoices_with_total = (
        db.scalar(select(func.count(Invoice.id)).where(Invoice.total > 0)) or 0
    )
    unmatched = (
        db.scalar(
            select(func.count(SellableItem.id)).where(
                SellableItem.recipe_id.is_(None),
                SellableItem.product_id.is_(None),
            )
        )
        or 0
    )
    linked = (
        db.scalar(
            select(func.count(SellableItem.id)).where(
                (SellableItem.recipe_id.is_not(None)) | (SellableItem.product_id.is_not(None))
            )
        )
        or 0
    )
    return {
        "recipes": int(recipes),
        "invoices": int(invoices),
        "invoices_with_total": int(invoices_with_total),
        "unmatched": int(unmatched),
        "linked": int(linked),
    }
