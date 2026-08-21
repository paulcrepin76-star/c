from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.connections import extra_dict, get_connection, set_extra
from app.costing import money
from app.models import CollectorRun, CostSnapshot, PurchasePrice, Recipe
from app.purchasing import purchasing_board
from app.services import recipe_cost

BROWSER_SOURCES = (
    ("chefs-warehouse", "Chef's Warehouse"),
    ("gordon", "Gordon Food Service"),
    ("sams-club", "Sam's Club"),
    ("costco", "Costco"),
    ("restaurant-depot", "Restaurant Depot"),
    ("webstaurantstore", "WebstaurantStore"),
    ("publix", "Publix"),
    ("walmart", "Walmart"),
    ("target", "Target"),
    ("aldi", "Aldi"),
)

# Guest Chromium is enough. No membership login.
PUBLIC_BROWSER_SLUGS = {"webstaurantstore", "publix", "walmart", "target", "aldi"}


def set_browser_status(db: Session, slug: str, status: str, error: str = "") -> None:
    row = get_connection(db, slug)
    payload = {
        "browser_status": status,
        "browser_error": error[:240],
    }
    if status == "ready":
        payload["browser_success_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
        payload["browser_error"] = ""
    set_extra(row, **payload)
    if status == "needs_reauth" and error:
        row.last_error = f"Browser: {error[:200]}"
    db.commit()


def browser_status_for(db: Session, slug: str) -> dict:
    row = get_connection(db, slug)
    extra = extra_dict(row)
    status = str(extra.get("browser_status") or "never_logged_in")
    return {
        "slug": slug,
        "status": status,
        "error": str(extra.get("browser_error") or ""),
        "success_at": str(extra.get("browser_success_at") or ""),
    }


def snapshot_recipe_costs(db: Session, captured_on: date | None = None) -> int:
    captured_on = captured_on or date.today()
    written = 0
    recipes = db.query(Recipe).all()
    for recipe in recipes:
        lines = [(line.qty, line.product.current_cost) for line in recipe.lines]
        cost = recipe_cost(lines)
        row = (
            db.query(CostSnapshot)
            .filter(
                CostSnapshot.captured_on == captured_on,
                CostSnapshot.kind == "recipe",
                CostSnapshot.ref_id == recipe.id,
            )
            .first()
        )
        if row is None:
            row = CostSnapshot(captured_on=captured_on, kind="recipe", ref_id=recipe.id)
            db.add(row)
        row.name = recipe.name
        row.cost = cost
        written += 1
    db.commit()
    return written


def save_collector_run(db: Session, payload: dict) -> CollectorRun:
    def _dt(value):
        if not value:
            return datetime.now(UTC).replace(tzinfo=None)
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", ""))
        except ValueError:
            return datetime.now(UTC).replace(tzinfo=None)

    run = CollectorRun(
        started_at=_dt(payload.get("started_at")),
        finished_at=_dt(payload.get("finished_at")),
        checked=int(payload.get("checked") or 0),
        updated=int(payload.get("updated") or 0),
        unchanged=int(payload.get("unchanged") or 0),
        unavailable=int(payload.get("unavailable") or 0),
        needs_reauth=",".join(payload.get("needs_reauth") or []),
        sources_json=json.dumps(payload.get("sources") or [])[:8000],
    )
    db.add(run)
    for slug in payload.get("needs_reauth") or []:
        set_browser_status(db, slug, "needs_reauth", "Session expired or blocked. Log in again.")
    db.commit()
    snapshot_recipe_costs(db)
    return run


def latest_run(db: Session) -> CollectorRun | None:
    return db.query(CollectorRun).order_by(CollectorRun.id.desc()).first()


def overnight_report(db: Session) -> dict:
    run = latest_run(db)
    board = purchasing_board(db)
    opportunities = []
    monthly = Decimal("0")
    for card in board["cards"]:
        if card["recommend"] not in ("switch", "consider"):
            continue
        opportunities.append(
            {
                "product": card["product"].name,
                "you_pay": f"{card['current'].supplier.name} {money(card['current'].unit_cost_compare)}/{card['compare_unit']}"
                if card["current"].supplier
                else "",
                "best": f"{card['cheapest'].supplier.name} {money(card['cheapest'].unit_cost_compare)}/{card['compare_unit']}"
                if card["cheapest"].supplier
                else "",
                "gap_pct": card["gap_pct"],
                "monthly": card["net"],
            }
        )
        monthly += Decimal(str(card["net"] or 0))
    today = date.today()
    promos = (
        db.query(PurchasePrice)
        .filter(PurchasePrice.is_discounted.is_(True), PurchasePrice.purchased_on >= today)
        .order_by(PurchasePrice.id.desc())
        .limit(12)
        .all()
    )
    promo_rows = [
        {
            "product": row.product.name if row.product else "",
            "supplier": row.supplier.name if row.supplier else "",
            "pack_price": row.pack_price,
            "unit_cost": row.unit_cost_compare,
        }
        for row in promos
    ]
    yesterday = (
        db.query(CostSnapshot)
        .filter(CostSnapshot.kind == "recipe", CostSnapshot.captured_on < today)
        .order_by(CostSnapshot.captured_on.desc())
        .all()
    )
    latest_day = yesterday[0].captured_on if yesterday else None
    prev = {row.ref_id: row for row in yesterday if latest_day and row.captured_on == latest_day}
    today_snaps = (
        db.query(CostSnapshot).filter(CostSnapshot.kind == "recipe", CostSnapshot.captured_on == today).all()
    )
    recipe_moves = []
    for snap in today_snaps:
        old = prev.get(snap.ref_id)
        if old is None:
            continue
        delta = Decimal(str(snap.cost)) - Decimal(str(old.cost))
        if delta == 0:
            continue
        recipe_moves.append(
            {
                "recipe": snap.name,
                "yesterday": old.cost,
                "today": snap.cost,
                "delta": money(delta),
            }
        )
    recipe_moves.sort(key=lambda item: Decimal(str(item["delta"])))
    return {
        "run": run,
        "checked": run.checked if run else 0,
        "updated": run.updated if run else 0,
        "unchanged": run.unchanged if run else 0,
        "unavailable": run.unavailable if run else 0,
        "needs_reauth": [part for part in (run.needs_reauth.split(",") if run else []) if part],
        "opportunities": opportunities[:12],
        "monthly_total": money(monthly),
        "promos": promo_rows,
        "recipes": recipe_moves[:12],
    }
