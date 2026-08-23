"""Honest report health: do not treat missing inputs as a finished P&L."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connections import extra_dict, get_connection
from app.costing import money
from app.models import InventoryCount, Invoice, Sale, SellableItem
from app.quickbooks import _qb_is_sandbox
from app.services import catalog_counts


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def mapping_coverage(db: Session, start: date, end: date) -> dict:
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    rows = db.execute(
        select(Sale.revenue, SellableItem.recipe_id, SellableItem.product_id)
        .join(SellableItem, SellableItem.id == Sale.sellable_item_id)
        .where(Sale.sold_at >= start_dt, Sale.sold_at <= end_dt)
    ).all()
    mapped = money(0)
    unmapped = money(0)
    for revenue, recipe_id, product_id in rows:
        amount = money(revenue or 0)
        if recipe_id or product_id:
            mapped += amount
        else:
            unmapped += amount
    total = money(mapped + unmapped)
    unmapped_pct = money((unmapped / total) * 100) if total else money(0)
    return {
        "mapped_sales": mapped,
        "unmapped_sales": unmapped,
        "total_sales": total,
        "unmapped_pct": unmapped_pct,
    }


def data_health(db: Session, start: date, end: date, board: dict | None = None) -> dict:
    counts = catalog_counts(db)
    coverage = mapping_coverage(db, start, end)
    square = get_connection(db, "square")
    paperless = get_connection(db, "paperless")
    quickbooks = get_connection(db, "quickbooks")
    extra = extra_dict(quickbooks)
    last_sale = db.scalar(select(func.max(Sale.sold_at)))
    last_invoice = db.scalar(select(func.max(Invoice.issued_on)))
    last_count = db.scalar(select(func.max(InventoryCount.counted_at)))
    today = datetime.now(UTC).replace(tzinfo=None).date()
    last_sale_day = _as_date(last_sale)
    stale_days = (today - last_sale_day).days if last_sale_day else None
    sales = money((board or {}).get("net_sales") or coverage["total_sales"])
    spend = money((board or {}).get("categorized_spend") or 0)
    item_total = counts["linked"] + counts["unmatched"]
    match_item_pct = money((counts["linked"] / item_total) * 100) if item_total else money(0)
    sales_thin = bool(spend > 0 and (sales <= 0 or spend > sales * 8))
    sale_stale = stale_days is None or stale_days > 5
    if square.status != "connected" or sales_thin or (sale_stale and spend > sales):
        confidence = "unreliable"
    elif coverage["unmapped_pct"] >= 25 or counts["unmatched"] > 20:
        confidence = "partial"
    else:
        confidence = "complete"
    if sales_thin:
        summary = "Square sales for this window look too small next to filed bills. Operating profit is hidden."
    elif square.status != "connected":
        summary = "Square is not connected. Sales and profit stay incomplete."
    elif coverage["unmapped_pct"] >= 25:
        summary = f"Incomplete — {coverage['unmapped_pct']:.0f}% of sales unmapped to recipes."
    elif counts["unmatched"] > 20:
        summary = f"{counts['unmatched']} Square items still need a recipe. Food cost is a guess."
    else:
        summary = "Sources look complete enough for this window."
    accounting = "sandbox" if _qb_is_sandbox(extra) else ("live" if quickbooks.status == "connected" else "not connected")
    return {
        "confidence": confidence,
        "summary": summary,
        "show_profit": confidence != "unreliable",
        "show_food_cost": coverage["unmapped_pct"] < 25 and coverage["mapped_sales"] > 0,
        "square_status": square.status,
        "square_last": last_sale_day,
        "square_sync": _as_date(square.updated_at),
        "paperless_status": paperless.status,
        "invoice_last": last_invoice,
        "match_item_pct": match_item_pct,
        "unmatched": counts["unmatched"],
        "linked": counts["linked"],
        "unmapped_pct": coverage["unmapped_pct"],
        "mapped_sales": coverage["mapped_sales"],
        "unmapped_sales": coverage["unmapped_sales"],
        "inventory_last": _as_date(last_count),
        "labor": "none",
        "accounting": accounting,
        "coverage": coverage,
        "counts": counts,
    }
