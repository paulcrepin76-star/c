"""Read-only QuickBooks Online: P&L and expenses. Square stays the sales number."""

from __future__ import annotations

import base64
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.connections import access_token_for, extra_dict, get_connection, mark_connected, mark_error, set_extra
from app.costing import money
from app.ingest import INVOICE_TOTAL_MAX, PURCHASE_INVOICE_TYPES
from app.models import Invoice, Sale, SellableItem
from app.services import period_costing

TIMEOUT = httpx.Timeout(25.0, connect=8.0)
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
ACCOUNTING_SCOPE = "com.intuit.quickbooks.accounting"
USER_AGENT = "SurveyCafeCellar/1.0"

# First match wins. Income is first so "Sales" never lands in expenses.
GROUP_RULES = (
    ("income", ("sales", "income", "revenue", "gratuity", "tips income", "service charge", "other income")),
    ("cogs_wine", ("wine", "liquor", "beer", "alcohol", "spirits", "bar cost")),
    ("cogs_food", ("cogs", "cost of goods", "cost of sales", "food", "meat", "seafood", "produce", "dairy", "bakery", "grocery", "inventory", "beverage", "coffee", "packaging", "to-go", "to go")),
    ("labor", ("payroll", "wage", "wages", "salary", "salaries", "labor", "officer", "benefits", "payroll tax", "workers comp", "worker's comp", "contractor")),
    ("occupancy", ("rent", "cam ", "common area", "lease", "occupancy", "mortgage")),
    ("utilities", ("electric", "fpl", "water", "utility", "utilities", "waste", "garbage", "trash", "internet", "phone", "comcast", "pest")),
    ("fees", ("square", "merchant", "processing", "bank fee", "bank charge", "stripe", "card fee")),
    ("insurance", ("insurance",)),
    ("repairs", ("repair", "maintenance", "equipment")),
    ("software", ("software", "subscription", "saas", "pos software")),
    ("marketing", ("marketing", "advertis", "promotion", "promo")),
)

DISPLAY_GROUPS = (
    ("cogs_food", "Food COGS"),
    ("cogs_wine", "Beverage COGS"),
    ("labor", "Labor"),
    ("occupancy", "Rent / occupancy"),
    ("utilities", "Utilities"),
    ("fees", "Merchant fees"),
    ("insurance", "Insurance"),
    ("repairs", "Repairs"),
    ("software", "Software"),
    ("marketing", "Marketing"),
    ("linen", "Linen / uniforms"),
    ("other", "Other operating"),
)

# Vendor / title needles for filed invoices. First match wins.
# Do not map leftover internals here — those stay on the review list.
EXPENSE_VENDOR_RULES = (
    ("cogs_wine", ("pg fine", "wine distributor", "wine house")),
    ("cogs_food", (
        "sam's", "sams club", "sams-club", "samsclub",
        "chef's warehouse", "chefs warehouse",
        "restaurant depot", "gordon", "gfs",
        "st. armands", "st armands", "laubry",
        "stan's coffee", "stans coffee", "bee farm",
        "publix", "aldi", "costco", "metro france",
    )),
    ("insurance", ("biberk", "bi berk", "insurance")),
    ("utilities", ("fpl", "florida power", "comcast", "bonita springs water", "pest", "sanitation", "grease trap", "waste")),
    ("repairs", ("parts town", "refrigeration", "air &", "air and", "easy ice", "sea air", "home depot")),
    ("occupancy", ("tuff shed", "rent")),
    ("marketing", ("presstige", "musthavemenus", "must have menus", "printing")),
    ("linen", ("vestis", "aramark", "uniform")),
    ("other", ("notaire", "maitre", "maître", "uline", "webstaurant", "legal")),
)
OPERATING_KEYS = ("occupancy", "utilities", "fees", "insurance", "repairs", "software", "marketing", "linen", "other")
FINANCE_VIEWS = ("overview", "sales", "vendors")
GROUP_LABELS = {key: label for key, label in DISPLAY_GROUPS}
GROUP_LABELS["uncategorized"] = "Needs a category"


def oauth_public_url() -> str:
    return (settings.resto_oauth_url or settings.resto_public_url).rstrip("/")


def qb_callback_url() -> str:
    return oauth_public_url() + "/connect/quickbooks/callback"


def qb_app_creds(db: Session) -> tuple[str, str, str]:
    extra = extra_dict(get_connection(db, "quickbooks"))
    app_id = str(extra.get("application_id") or settings.quickbooks_client_id or "").strip()
    app_secret = str(extra.get("application_secret") or settings.quickbooks_client_secret or "").strip()
    environment = str(extra.get("environment") or settings.quickbooks_environment or "production").strip() or "production"
    return app_id, app_secret, environment


def qb_api_host(environment: str) -> str:
    if environment == "sandbox":
        return "https://sandbox-quickbooks.api.intuit.com"
    return "https://quickbooks.api.intuit.com"


def _basic_auth(app_id: str, app_secret: str) -> str:
    raw = f"{app_id}:{app_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def expense_group(vendor: str = "", title: str = "", invoice_type: str = "") -> str:
    """Map a filed bill to a cafe group without changing the invoice type."""
    blob = f"{vendor} {title}".lower()
    if "not an invoice" in blob:
        return "skip"
    if "needs review" in blob or "card approval" in blob:
        return "uncategorized"
    if "internal revenue" in blob:
        return "uncategorized"
    for group, needles in EXPENSE_VENDOR_RULES:
        if any(needle in blob for needle in needles):
            return group
    if "internal" in blob and ("menu" in blob or "proof for order" in blob):
        return "marketing"
    if invoice_type == "wine":
        return "cogs_wine"
    if invoice_type == "utility":
        return "utilities"
    if invoice_type == "ignore":
        return "skip"
    return "uncategorized"


def map_account(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    if not text or text.startswith("total "):
        return "skip"
    for group, needles in GROUP_RULES:
        if any(needle in text for needle in needles):
            return group
    return "other"


def _as_money(value) -> Decimal:
    if value in (None, ""):
        return money(0)
    try:
        return money(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return money(0)


def flatten_pnl(payload: dict) -> list[dict]:
    rows_node = (payload or {}).get("Rows") or {}
    raw = rows_node.get("Row") or []
    if isinstance(raw, dict):
        raw = [raw]
    found: list[dict] = []

    def walk(node, section: str = "") -> None:
        if isinstance(node, list):
            for child in node:
                walk(child, section)
            return
        if not isinstance(node, dict):
            return
        header_cols = ((node.get("Header") or {}).get("ColData") or [{}])
        header = str((header_cols[0] or {}).get("value") or section)
        if node.get("type") == "Data":
            cols = node.get("ColData") or []
            name = str((cols[0] or {}).get("value") or "")
            amount = _as_money((cols[-1] or {}).get("value") if len(cols) > 1 else 0)
            group = map_account(name)
            if group != "skip" and name:
                found.append({"name": name, "amount": amount, "group": group, "section": header})
        nested = (node.get("Rows") or {}).get("Row") or []
        walk(nested, header or section)

    walk(raw)
    return found


def rollup(lines: list[dict]) -> dict[str, Decimal]:
    buckets = {key: money(0) for key, _label in DISPLAY_GROUPS}
    buckets["income"] = money(0)
    buckets["cogs"] = money(0)
    buckets["uncategorized"] = money(0)
    for line in lines:
        group = line.get("group") or "other"
        amount = money(line.get("amount") or 0)
        if group in {"skip", ""}:
            continue
        if group == "income":
            buckets["income"] += amount
            continue
        if group == "uncategorized":
            buckets["uncategorized"] += amount
            continue
        if group not in buckets:
            group = "other"
        buckets[group] += amount
    buckets["cogs"] = buckets["cogs_food"] + buckets["cogs_wine"]
    return buckets


def finance_view(kind: str | None = None) -> str:
    return kind if kind in FINANCE_VIEWS else "overview"


def _iter_months(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        yield cursor
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def _month_shell(start: date, end: date) -> dict[str, dict]:
    months = {}
    for cursor in _iter_months(start, end):
        months[cursor.strftime("%Y-%m")] = {
            "key": cursor.strftime("%Y-%m"),
            "label": cursor.strftime("%b"),
            "sales": 0.0,
            "spend": 0.0,
            "tickets": set(),
        }
    return months


def square_item_rows(db: Session, start: date, end: date, limit: int = 15) -> list[dict]:
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    rows = db.execute(
        select(
            func.coalesce(SellableItem.name, "Unmatched item"),
            func.coalesce(func.sum(Sale.revenue), 0),
            func.coalesce(func.sum(Sale.qty), 0),
        )
        .select_from(Sale)
        .outerjoin(SellableItem, SellableItem.id == Sale.sellable_item_id)
        .where(Sale.sold_at >= start_dt, Sale.sold_at <= end_dt)
        .group_by(func.coalesce(SellableItem.name, "Unmatched item"))
        .order_by(func.coalesce(func.sum(Sale.revenue), 0).desc())
        .limit(limit)
    ).all()
    return [
        {"name": str(name), "amount": money(total), "qty": money(qty)}
        for name, total, qty in rows
        if money(total) > 0
    ]


def square_month_sales(db: Session, start: date, end: date) -> dict[str, dict]:
    months = _month_shell(start, end)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    for sold_at, revenue, order_id in db.execute(
        select(Sale.sold_at, Sale.revenue, Sale.square_order_id).where(Sale.sold_at >= start_dt, Sale.sold_at <= end_dt)
    ):
        if not sold_at:
            continue
        key = sold_at.strftime("%Y-%m")
        if key not in months:
            continue
        months[key]["sales"] = round(months[key]["sales"] + float(revenue or 0), 2)
        if order_id:
            months[key]["tickets"].add(order_id)
    return months


def vendor_rows(lines: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for line in lines:
        name = str(line.get("name") or "Unknown")
        group = str(line.get("group") or "uncategorized")
        amount = money(line.get("amount") or 0)
        row = buckets.setdefault(
            name,
            {"name": name, "group": group, "label": GROUP_LABELS.get(group, group), "bills": 0, "amount": money(0)},
        )
        row["bills"] += 1
        row["amount"] = money(row["amount"] + amount)
        if group != row["group"] and group != "uncategorized":
            row["group"] = group
            row["label"] = GROUP_LABELS.get(group, group)
    ranked = sorted(buckets.values(), key=lambda row: row["amount"], reverse=True)
    total = sum((row["amount"] for row in ranked), money(0))
    for row in ranked:
        row["pct"] = money((row["amount"] / total) * 100) if total else money(0)
    return ranked


def finance_period(kind: str | None = None) -> tuple[str, date, date]:
    today = datetime.now(UTC).replace(tzinfo=None).date()
    key = kind if kind in {"month", "last", "90", "ytd"} else "ytd"
    if key == "last":
        first_this = today.replace(day=1)
        last = first_this - timedelta(days=1)
        return key, last.replace(day=1), last
    if key == "90":
        return key, today - timedelta(days=90), today
    if key == "ytd":
        return key, date(today.year, 1, 1), today
    return key, today.replace(day=1), today


def paperless_expense_lines(db: Session, start: date, end: date) -> list[dict]:
    rows = (
        db.query(Invoice)
        .options(joinedload(Invoice.supplier))
        .filter(
            Invoice.issued_on.is_not(None),
            Invoice.issued_on >= start,
            Invoice.issued_on <= end,
            Invoice.total > 0,
            Invoice.total <= INVOICE_TOTAL_MAX,
        )
        .all()
    )
    lines = []
    for invoice in rows:
        vendor = invoice.supplier.name if invoice.supplier else (invoice.title or invoice.number or "Unknown")
        group = expense_group(vendor, invoice.title or "", invoice.invoice_type)
        if group == "skip":
            continue
        lines.append(
            {
                "name": vendor,
                "title": invoice.title or "",
                "amount": money(invoice.total or 0),
                "group": group,
                "invoice_type": invoice.invoice_type,
                "issued_on": invoice.issued_on,
            }
        )
    return lines


def paperless_purchases(db: Session, start: date, end: date) -> Decimal:
    total = money(0)
    rows = (
        db.query(Invoice)
        .filter(
            Invoice.issued_on.is_not(None),
            Invoice.issued_on >= start,
            Invoice.issued_on <= end,
            Invoice.invoice_type.in_(PURCHASE_INVOICE_TYPES),
            Invoice.total > 0,
            Invoice.total <= INVOICE_TOTAL_MAX,
        )
        .all()
    )
    for invoice in rows:
        total += money(invoice.total or 0)
    return total


def _token_expired(extra: dict) -> bool:
    stamp = str(extra.get("token_expires_at") or "")
    if not stamp:
        return True
    try:
        expires = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return expires <= datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=2)


def refresh_access_token(db: Session) -> str:
    row = get_connection(db, "quickbooks")
    app_id, app_secret, _env = qb_app_creds(db)
    refresh = row.refresh_token
    if not app_id or not app_secret or not refresh:
        return access_token_for(db, "quickbooks")
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                TOKEN_URL,
                headers={
                    "Authorization": _basic_auth(app_id, app_secret),
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh},
            )
            response.raise_for_status()
            payload = response.json()
        access = payload.get("access_token") or ""
        new_refresh = payload.get("refresh_token") or refresh
        expires_in = int(payload.get("expires_in") or 3600)
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=max(expires_in - 60, 60))
        extra = extra_dict(row)
        mark_connected(
            db,
            "quickbooks",
            access,
            refresh_token=new_refresh,
            realm_id=extra.get("realm_id"),
            environment=extra.get("environment"),
            application_id=extra.get("application_id"),
            application_secret=extra.get("application_secret"),
            company=extra.get("company"),
            token_expires_at=expires_at.isoformat(),
            token_type="oauth",
        )
        return access
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "quickbooks", str(exc))
        return access_token_for(db, "quickbooks")


def valid_access_token(db: Session) -> str:
    extra = extra_dict(get_connection(db, "quickbooks"))
    token = access_token_for(db, "quickbooks")
    if not token:
        return ""
    if extra.get("token_type") == "oauth" and _token_expired(extra):
        return refresh_access_token(db)
    return token


def fetch_profit_and_loss(db: Session, start: date, end: date) -> dict:
    row = get_connection(db, "quickbooks")
    extra = extra_dict(row)
    realm_id = str(extra.get("realm_id") or "")
    environment = str(extra.get("environment") or "production")
    token = valid_access_token(db)
    if not token or not realm_id:
        return {"status": "skipped", "reason": "not connected", "lines": []}
    host = qb_api_host(environment)
    url = f"{host}/v3/company/{realm_id}/reports/ProfitAndLoss"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(
                url,
                headers=_headers(token),
                params={"start_date": start.isoformat(), "end_date": end.isoformat(), "minorversion": "75"},
            )
            if response.status_code == 401:
                token = refresh_access_token(db)
                response = client.get(
                    url,
                    headers=_headers(token),
                    params={"start_date": start.isoformat(), "end_date": end.isoformat(), "minorversion": "75"},
                )
            response.raise_for_status()
            payload = response.json()
        lines = flatten_pnl(payload)
        set_extra(
            get_connection(db, "quickbooks"),
            last_report={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "lines": [{"name": line["name"], "amount": str(line["amount"]), "group": line["group"]} for line in lines],
                "fetched_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            },
        )
        db.commit()
        return {"status": "ok", "lines": lines, "company": extra.get("company") or ""}
    except Exception as exc:  # noqa: BLE001
        mark_error(db, "quickbooks", str(exc))
        cached = extra.get("last_report") or {}
        cached_lines = []
        for line in cached.get("lines") or []:
            cached_lines.append(
                {"name": line.get("name"), "amount": _as_money(line.get("amount")), "group": line.get("group") or "other"}
            )
        if cached_lines:
            return {"status": "cached", "lines": cached_lines, "error": str(exc)[:200], "company": extra.get("company") or ""}
        return {"status": "error", "error": str(exc)[:200], "lines": []}


def sync_quickbooks(db: Session) -> dict:
    if not access_token_for(db, "quickbooks"):
        return {"status": "skipped", "reason": "not connected"}
    extra = extra_dict(get_connection(db, "quickbooks"))
    if _qb_is_sandbox(extra):
        return {"status": "skipped", "reason": "sandbox"}
    _kind, start, end = finance_period("ytd")
    result = fetch_profit_and_loss(db, start, end)
    return {"status": result.get("status"), "lines": len(result.get("lines") or []), "error": result.get("error")}


def _qb_is_sandbox(extra: dict) -> bool:
    company = str(extra.get("company") or extra.get("company_name") or "").lower()
    env = str(extra.get("environment") or "").lower()
    return env == "sandbox" or "sandbox" in company


def finance_board(db: Session, start: date, end: date, qb_lines: list[dict] | None = None) -> dict:
    """Square is sales. Recategorized invoices are expenses until live QuickBooks is connected."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    costing = period_costing(db, start_dt, end_dt)
    sales = costing["period_sales"]
    purchases = paperless_purchases(db, start, end)
    paper_lines = paperless_expense_lines(db, start, end)
    paper = rollup(paper_lines)
    uncategorized = sorted(
        [line for line in paper_lines if line["group"] == "uncategorized"],
        key=lambda line: (line["amount"], str(line.get("name") or "")),
        reverse=True,
    )
    row = get_connection(db, "quickbooks")
    extra = extra_dict(row)
    sandbox = _qb_is_sandbox(extra)
    connected = bool(row.access_token) or bool(access_token_for(db, "quickbooks"))
    lines = list(qb_lines) if qb_lines is not None else []
    fetched = "local"
    if qb_lines is None and connected and not sandbox:
        result = fetch_profit_and_loss(db, start, end)
        lines = result.get("lines") or []
        fetched = result.get("status") or "ok"
    elif sandbox and connected:
        fetched = "sandbox-ignored"
    qb = rollup(lines)
    use_qb = bool(lines) and (
        qb["cogs"] > 0 or any(qb[key] > 0 for key in OPERATING_KEYS) or qb["labor"] > 0
    )
    if use_qb:
        buckets = qb
        cogs = qb["cogs"] if qb["cogs"] > 0 else paper["cogs"]
        cogs_source = "quickbooks" if qb["cogs"] > 0 else "paperless"
        expense_source = "quickbooks"
        labor = qb["labor"]
        food = qb["cogs_food"] if qb["cogs"] > 0 else paper["cogs_food"]
        wine = qb["cogs_wine"] if qb["cogs"] > 0 else paper["cogs_wine"]
        qb_income = qb["income"]
    else:
        buckets = paper
        cogs = paper["cogs"]
        cogs_source = "paperless"
        expense_source = "paperless"
        labor = paper["labor"]
        food = paper["cogs_food"]
        wine = paper["cogs_wine"]
        qb_income = money(0)
    operating = money(0)
    detail = []
    for key, label in DISPLAY_GROUPS:
        if key == "cogs_food":
            amount = food
        elif key == "cogs_wine":
            amount = wine
        elif key == "labor":
            amount = labor
        else:
            amount = buckets[key]
            operating += amount
        detail.append({"key": key, "label": label, "amount": amount})
    gross = money(sales - cogs)
    prime = money(cogs + labor)
    profit = money(sales - cogs - labor - operating)
    sales_num = sales if sales else money(0)

    def pct(part: Decimal) -> Decimal:
        if sales_num <= 0:
            return money(0)
        return money((part / sales_num) * 100)

    months = square_month_sales(db, start, end)
    for line in paper_lines:
        if line["group"] in {"skip", "uncategorized"} or not line.get("issued_on"):
            continue
        key = line["issued_on"].strftime("%Y-%m")
        if key in months:
            months[key]["spend"] = round(months[key]["spend"] + float(line["amount"]), 2)
    month_rows = [months[key] for key in sorted(months)]
    tickets = set()
    for month in month_rows:
        tickets.update(month["tickets"])
    ticket_count = len(tickets)
    avg_ticket = money(sales / ticket_count) if ticket_count else money(0)
    mix = [
        {"name": key, "amount": float(bucket["sales"])}
        for key, bucket in costing["groups"].items()
        if bucket["sales"] > 0
    ]
    expense_mix = [
        {"name": item["label"], "key": item["key"], "amount": float(item["amount"])}
        for item in detail
        if item["amount"] > 0
    ]
    vendors = vendor_rows(paper_lines)
    categorized_spend = money(cogs + labor + operating)

    return {
        "start": start,
        "end": end,
        "connected": connected,
        "company": extra.get("company") or "",
        "sandbox": sandbox,
        "fetched": fetched,
        "net_sales": sales,
        "qb_income": qb_income,
        "purchases": purchases,
        "cogs": cogs,
        "cogs_food": food,
        "cogs_wine": wine,
        "cogs_source": cogs_source,
        "expense_source": expense_source,
        "paperless_cogs": paper["cogs"],
        "gross_profit": gross,
        "labor": labor,
        "prime": prime,
        "operating": operating,
        "operating_profit": profit,
        "uncategorized": uncategorized,
        "uncategorized_total": paper["uncategorized"],
        "sales_pct": pct(sales_num),
        "cogs_pct": pct(cogs),
        "cogs_food_pct": pct(food),
        "cogs_wine_pct": pct(wine),
        "gross_pct": pct(gross),
        "labor_pct": pct(labor),
        "prime_pct": pct(prime),
        "profit_pct": pct(profit),
        "detail": detail,
        "lines": [line for line in lines if line.get("group") != "income"],
        "status": row.status,
        "last_error": row.last_error,
        "categorized_spend": categorized_spend,
        "tickets": ticket_count,
        "avg_ticket": avg_ticket,
        "vendor_count": len(vendors),
        "top_items": square_item_rows(db, start, end),
        "vendors": vendors,
        "mix": mix,
        "expense_mix": expense_mix,
        "charts": {
            "labels": [row["label"] for row in month_rows],
            "sales": [row["sales"] for row in month_rows],
            "spend": [row["spend"] for row in month_rows],
            "mix": mix,
            "expense_mix": expense_mix,
        },
    }


def store_oauth_tokens(db: Session, payload: dict, realm_id: str, environment: str, company: str = "") -> None:
    access = payload.get("access_token") or ""
    refresh = payload.get("refresh_token") or ""
    expires_in = int(payload.get("expires_in") or 3600)
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=max(expires_in - 60, 60))
    extra = extra_dict(get_connection(db, "quickbooks"))
    mark_connected(
        db,
        "quickbooks",
        access,
        refresh_token=refresh,
        realm_id=realm_id,
        environment=environment,
        application_id=extra.get("application_id"),
        application_secret=extra.get("application_secret"),
        company=company,
        token_expires_at=expires_at.isoformat(),
        token_type="oauth",
    )


def fetch_company_name(token: str, realm_id: str, environment: str) -> str:
    if not token or not realm_id:
        return ""
    host = qb_api_host(environment)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(
                f"{host}/v3/company/{realm_id}/companyinfo/{realm_id}",
                headers=_headers(token),
                params={"minorversion": "75"},
            )
            if response.status_code >= 400:
                return ""
            info = (response.json().get("CompanyInfo") or {})
            return str(info.get("CompanyName") or info.get("LegalName") or "")[:160]
    except Exception:  # noqa: BLE001
        return ""
