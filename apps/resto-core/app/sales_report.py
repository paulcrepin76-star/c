"""Detailed Square sales and vendor reports. Square stays the sales number."""

from __future__ import annotations

from calendar import day_name
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.costing import money
from app.models import Sale, SellableItem
from app.quickbooks import paperless_expense_lines, vendor_rows

# First match wins. Gift cards stay out of food.
SALES_CATEGORY_RULES = (
    ("Gift cards", ("gift card", "egift")),
    ("Coffee", ("coffee", "espresso", "latte", "cappuccino", "macchiato", "mocha", "cafe cuban", "americano", "cortado")),
    ("Tea & juice", ("iced tea", "hot tea", "chai", "smoothie", "orange juice", "juice", "lemonade")),
    ("Soda & water", ("coca", "coke", "soda", "sprite", "perrier", "water")),
    ("Wine", ("wine", "sancerre", "chardonnay", "cabernet", "pinot", "prosecco", "champagne", "rosé", "rose ", "parisot", "sauvignon", "merlot", "cote de")),
    ("Beer", ("beer", "ipa")),
    ("Cocktails", ("mimosa", "bloody", "sangria", "cocktail", "spritz", "old fashioned")),
    ("Crepes", ("crepe", "ficelle", "mongolfiere")),
    ("Breakfast plates", ("breakfast plate", "omelette", "omelet", "quiche", "benedict", "scrambel", "scrambl", "pancake", "french toast", "oatmeal")),
    ("Wraps & biscuits", ("wrap", "biscuit")),
    ("Sandwiches", ("sandwich", "reuben", "croque", "panini", "burger", "parisian", "bagnat", "turkey bite", "blt")),
    ("Plates & dinner", ("paella", "bourguignon", "poulet", "duck", "lamb", "chicken", "normandy", "escargot", "shank", "provencal", "provençal")),
    ("Salads", ("salad", "salade", "nicoise", "ceasar", "caesar")),
    ("Pastry & dessert", ("croissant", "pie", "muffin", "creme", "brûlée", "brulee", "meringue", "yogurt", "almond")),
    ("Sides", ("bacon", "sausage", "potato", "fresh fruit", "avocado toast", "smoked salmon")),
)


def sales_category(name: str) -> str:
    blob = str(name or "").lower()
    if "gift" in blob and "card" in blob:
        return "Gift cards"
    for label, needles in SALES_CATEGORY_RULES:
        if any(needle in blob for needle in needles):
            return label
    return "Other menu"


def is_gift_card(name: str) -> bool:
    return sales_category(name) == "Gift cards"


def shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def prior_window(start: date, end: date) -> tuple[date, date]:
    return shift_year(start, -1), shift_year(end, -1)


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.max.time()).replace(microsecond=0)


def _change(now: Decimal, then: Decimal) -> dict:
    now = money(now)
    then = money(then)
    delta = money(now - then)
    pct = money((delta / then) * 100) if then else None
    return {"now": now, "then": then, "delta": delta, "pct": pct}


def _sale_rows(db: Session, start: date, end: date):
    start_dt, end_dt = _bounds(start, end)
    return db.execute(
        select(Sale.sold_at, Sale.revenue, Sale.qty, Sale.square_order_id, SellableItem.name)
        .select_from(Sale)
        .outerjoin(SellableItem, SellableItem.id == Sale.sellable_item_id)
        .where(Sale.sold_at >= start_dt, Sale.sold_at <= end_dt)
    ).all()


def _summarize(rows) -> dict:
    sales = money(0)
    qty = money(0)
    tickets: set[str] = set()
    items: dict[str, dict] = {}
    categories: dict[str, dict] = {}
    weekdays = {i: money(0) for i in range(7)}
    gifts = {"amount": money(0), "qty": money(0), "tickets": set()}
    for sold_at, revenue, line_qty, order_id, name in rows:
        amount = money(revenue or 0)
        count = money(line_qty or 0)
        label = str(name or "Unmatched item")
        group = sales_category(label)
        sales += amount
        qty += count
        if order_id:
            tickets.add(order_id)
        item = items.setdefault(label, {"name": label, "amount": money(0), "qty": money(0)})
        item["amount"] += amount
        item["qty"] += count
        cat = categories.setdefault(group, {"name": group, "amount": money(0), "qty": money(0), "items": 0})
        if item["qty"] == count:
            cat["items"] += 1
        cat["amount"] += amount
        cat["qty"] += count
        if sold_at:
            weekdays[sold_at.weekday()] += amount
        if group == "Gift cards":
            gifts["amount"] += amount
            gifts["qty"] += count
            if order_id:
                gifts["tickets"].add(order_id)
    ticket_count = len(tickets)
    return {
        "sales": sales,
        "qty": qty,
        "tickets": ticket_count,
        "avg_ticket": money(sales / ticket_count) if ticket_count else money(0),
        "items": items,
        "categories": categories,
        "weekdays": weekdays,
        "gifts": gifts,
    }


def _ranked_items(items: dict[str, dict], last_items: dict[str, dict], limit: int) -> list[dict]:
    ranked = sorted(items.values(), key=lambda row: row["amount"], reverse=True)[:limit]
    total = sum((row["amount"] for row in items.values()), money(0))
    rows = []
    for row in ranked:
        last = last_items.get(row["name"], {})
        change = _change(row["amount"], last.get("amount") or 0)
        rows.append(
            {
                "name": row["name"],
                "qty": money(row["qty"]),
                "amount": money(row["amount"]),
                "pct": money((row["amount"] / total) * 100) if total else money(0),
                "last": change["then"],
                "delta": change["delta"],
                "change_pct": change["pct"],
                "category": sales_category(row["name"]),
            }
        )
    return rows


def _ranked_categories(categories: dict[str, dict], last_cats: dict[str, dict], limit: int) -> list[dict]:
    ranked = sorted(categories.values(), key=lambda row: row["amount"], reverse=True)[:limit]
    total = sum((row["amount"] for row in categories.values()), money(0))
    rows = []
    for row in ranked:
        change = _change(row["amount"], (last_cats.get(row["name"]) or {}).get("amount") or 0)
        rows.append(
            {
                "name": row["name"],
                "qty": money(row["qty"]),
                "amount": money(row["amount"]),
                "pct": money((row["amount"] / total) * 100) if total else money(0),
                "last": change["then"],
                "delta": change["delta"],
                "change_pct": change["pct"],
            }
        )
    return rows


def category_board(db: Session, start: date, end: date, categories: tuple[str, ...] | list[str], limit: int = 40) -> dict:
    """Square items in one or more menu groups, compared to the same dates last year."""
    wanted = set(categories)
    prior_start, prior_end = prior_window(start, end)
    current = _summarize(_sale_rows(db, start, end))
    previous = _summarize(_sale_rows(db, prior_start, prior_end))
    items = {name: row for name, row in current["items"].items() if sales_category(name) in wanted}
    last_items = {name: row for name, row in previous["items"].items() if sales_category(name) in wanted}
    ranked = _ranked_items(items, last_items, limit)
    now = sum((row["amount"] for row in items.values()), money(0))
    then = sum((row["amount"] for row in last_items.values()), money(0))
    qty = sum((row["qty"] for row in items.values()), money(0))
    groups = []
    for name in categories:
        cat_now = current["categories"].get(name) or {}
        cat_then = previous["categories"].get(name) or {}
        change = _change(cat_now.get("amount") or 0, cat_then.get("amount") or 0)
        groups.append(
            {
                "name": name,
                "amount": change["now"],
                "last": change["then"],
                "delta": change["delta"],
                "change_pct": change["pct"],
                "qty": money(cat_now.get("qty") or 0),
            }
        )
    return {
        "start": start,
        "end": end,
        "prior_start": prior_start,
        "prior_end": prior_end,
        "has_last_year": then > 0,
        "sales": _change(now, then),
        "qty": qty,
        "rows": ranked,
        "best": ranked[0] if ranked else None,
        "groups": groups,
    }


def sales_report(db: Session, start: date, end: date) -> dict:
    prior_start, prior_end = prior_window(start, end)
    current = _summarize(_sale_rows(db, start, end))
    previous = _summarize(_sale_rows(db, prior_start, prior_end))
    first = db.scalar(select(func.min(Sale.sold_at)))
    last = db.scalar(select(func.max(Sale.sold_at)))
    sales = _change(current["sales"], previous["sales"])
    tickets = _change(Decimal(current["tickets"]), Decimal(previous["tickets"]))
    avg = _change(current["avg_ticket"], previous["avg_ticket"])
    gifts = _change(current["gifts"]["amount"], previous["gifts"]["amount"])
    weekday = []
    for index in range(7):
        change = _change(current["weekdays"][index], previous["weekdays"][index])
        weekday.append({"name": day_name[index], "amount": change["now"], "last": change["then"], "delta": change["delta"]})
    from app.quickbooks import square_month_sales

    this_months = square_month_sales(db, start, end)
    last_months = square_month_sales(db, prior_start, prior_end)
    labels = [this_months[key]["label"] for key in sorted(this_months)]
    this_series = [this_months[key]["sales"] for key in sorted(this_months)]
    last_series = []
    for key in sorted(this_months):
        prior_key = f"{int(key[:4]) - 1}{key[4:]}"
        last_series.append((last_months.get(prior_key) or {"sales": 0.0})["sales"])
    return {
        "prior_start": prior_start,
        "prior_end": prior_end,
        "first_sale": first.date() if first else None,
        "last_sale": last.date() if last else None,
        "has_last_year": previous["sales"] > 0,
        "sales": sales,
        "tickets": tickets,
        "avg_ticket": avg,
        "qty": current["qty"],
        "gifts": {
            **gifts,
            "qty": money(current["gifts"]["qty"]),
            "last_qty": money(previous["gifts"]["qty"]),
            "share": money((current["gifts"]["amount"] / current["sales"]) * 100) if current["sales"] else money(0),
        },
        "top_items": _ranked_items(current["items"], previous["items"], 20),
        "categories": _ranked_categories(current["categories"], previous["categories"], 10),
        "weekday": weekday,
        "charts": {
            "labels": labels,
            "sales": this_series,
            "last_year": last_series,
            "categories": [{"name": row["name"], "amount": float(row["amount"])} for row in _ranked_categories(current["categories"], previous["categories"], 10)],
            "weekday": [{"name": row["name"], "amount": float(row["amount"])} for row in weekday],
        },
    }


def vendor_report(db: Session, start: date, end: date) -> dict:
    prior_start, prior_end = prior_window(start, end)
    lines = paperless_expense_lines(db, start, end)
    prior_lines = paperless_expense_lines(db, prior_start, prior_end)
    current = vendor_rows(lines)
    previous = {row["name"]: row for row in vendor_rows(prior_lines)}
    ranked = []
    for row in current:
        change = _change(row["amount"], (previous.get(row["name"]) or {}).get("amount") or 0)
        ranked.append(
            {
                **row,
                "last": change["then"],
                "delta": change["delta"],
                "change_pct": change["pct"],
            }
        )
    groups: dict[str, Decimal] = defaultdict(lambda: money(0))
    last_groups: dict[str, Decimal] = defaultdict(lambda: money(0))
    for row in current:
        groups[row["label"]] += row["amount"]
    for row in previous.values():
        last_groups[row["label"]] += row["amount"]
    group_rows = []
    for name, amount in sorted(groups.items(), key=lambda item: item[1], reverse=True):
        change = _change(amount, last_groups.get(name) or 0)
        group_rows.append({"name": name, "amount": change["now"], "last": change["then"], "delta": change["delta"], "change_pct": change["pct"]})
    return {
        "prior_start": prior_start,
        "prior_end": prior_end,
        "has_last_year": any((row.get("amount") or 0) > 0 for row in previous.values()),
        "top_vendors": ranked[:20],
        "vendors": ranked,
        "groups": group_rows,
        "vendor_count": len(ranked),
        "charts": {
            "groups": [{"name": row["name"], "amount": float(row["amount"])} for row in group_rows],
        },
    }
