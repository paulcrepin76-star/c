"""Manager home: Square, invoices, house, and wine in one desk."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.connections import get_connection
from app.health import data_health
from app.quickbooks import finance_board, finance_period
from app.sales_report import sales_report
from app.services import catalog_counts


def manager_home(db: Session, house: dict, report: dict) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    _, ytd_start, ytd_end = finance_period("ytd")
    today_sales = sales_report(db, today, today)
    month_sales = sales_report(db, month_start, today)
    ytd_sales = sales_report(db, ytd_start, ytd_end)
    month_board = finance_board(db, month_start, today)
    counts = catalog_counts(db)
    health = data_health(db, month_start, today, month_board)
    square = get_connection(db, "square")
    paperless = get_connection(db, "paperless")
    quickbooks = get_connection(db, "quickbooks")
    actions = []
    if house.get("alerts"):
        actions.append(
            {"title": f"{house['alerts']} fridge{'s' if house['alerts'] != 1 else ''} out of range", "href": "/house", "kind": "alert"}
        )
    if not health.get("inventory_last"):
        actions.append({"title": "Count a shelf so inventory is real", "href": "/inventory", "kind": "warn"})
    if month_board["uncategorized"]:
        actions.append(
            {
                "title": f"{len(month_board['uncategorized'])} bills need a category",
                "href": "/finance?view=vendors",
                "kind": "warn",
            }
        )
    if counts["unmatched"]:
        actions.append(
            {
                "title": f"{counts['unmatched']} Square items are not matched to recipes",
                "href": "/costing/match",
                "kind": "warn",
            }
        )
    for slug in report.get("needs_reauth") or []:
        actions.append({"title": f"Log in again: {slug}", "href": "/collector", "kind": "alert"})
    if square.status != "connected":
        actions.append({"title": "Connect Square so sales land here", "href": "/connect", "kind": "warn"})
    return {
        "today": today_sales,
        "month": month_sales,
        "ytd": ytd_sales,
        "board": month_board,
        "counts": counts,
        "health": health,
        "actions": actions,
        "uncategorized": len(month_board["uncategorized"]),
        "sources": {
            "square": square.status,
            "paperless": paperless.status,
            "quickbooks": quickbooks.status,
        },
        "connections": {
            "square": square.status == "connected",
            "paperless": paperless.status == "connected",
            "quickbooks": quickbooks.status == "connected",
        },
    }
