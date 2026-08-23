from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.connections import mark_connected
from app.db import SessionLocal
from app.main import app
from app.models import Invoice, Supplier
from app.quickbooks import expense_group, finance_board, finance_period, flatten_pnl, map_account, vendor_rows
from app.services import period_costing


SAMPLE_PNL = {
    "Rows": {
        "Row": [
            {
                "group": "Income",
                "Header": {"ColData": [{"value": "Income"}]},
                "Rows": {
                    "Row": [
                        {"type": "Data", "ColData": [{"value": "Sales of Product Income"}, {"value": "88000.00"}]},
                    ]
                },
            },
            {
                "group": "COGS",
                "Header": {"ColData": [{"value": "Cost of Goods Sold"}]},
                "Rows": {
                    "Row": [
                        {"type": "Data", "ColData": [{"value": "Food"}, {"value": "14500.00"}]},
                        {"type": "Data", "ColData": [{"value": "Wine Purchases"}, {"value": "1800.00"}]},
                    ]
                },
            },
            {
                "group": "Expenses",
                "Header": {"ColData": [{"value": "Expenses"}]},
                "Rows": {
                    "Row": [
                        {"type": "Data", "ColData": [{"value": "Payroll Wages"}, {"value": "20000.00"}]},
                        {"type": "Data", "ColData": [{"value": "Rent"}, {"value": "5400.00"}]},
                        {"type": "Data", "ColData": [{"value": "FPL Electric"}, {"value": "900.00"}]},
                        {"type": "Data", "ColData": [{"value": "Square Fees"}, {"value": "1900.00"}]},
                        {"type": "Data", "ColData": [{"value": "Insurance"}, {"value": "640.00"}]},
                        {"type": "Data", "ColData": [{"value": "Total Expenses"}, {"value": "28840.00"}]},
                    ]
                },
            },
        ]
    }
}


class QbClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        if "tokens/bearer" in url:
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: {"access_token": "qb-access", "refresh_token": "qb-refresh", "expires_in": 3600},
                "raise_for_status": lambda self: None,
            })()
        return type("R", (), {"status_code": 404, "json": lambda self: {}, "raise_for_status": lambda self: None})()

    def get(self, url, **kwargs):
        if "companyinfo" in url:
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: {"CompanyInfo": {"CompanyName": "Survey Cafe LLC"}},
            })()
        if "ProfitAndLoss" in url:
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: SAMPLE_PNL,
                "raise_for_status": lambda self: None,
            })()
        return type("R", (), {"status_code": 200, "json": lambda self: {}, "raise_for_status": lambda self: None})()


def test_account_mapping_puts_cafe_costs_in_groups():
    assert map_account("Sales of Product Income") == "income"
    assert map_account("Food") == "cogs_food"
    assert map_account("Wine Purchases") == "cogs_wine"
    assert map_account("Payroll Wages") == "labor"
    assert map_account("Rent") == "occupancy"
    assert map_account("FPL Electric") == "utilities"
    assert map_account("Square Fees") == "fees"
    assert map_account("Total Income") == "skip"


def test_square_sales_are_not_added_to_quickbooks_income():
    db = SessionLocal()
    try:
        end = date.today()
        start = end - timedelta(days=90)
        start_dt = __import__("datetime").datetime.combine(start, __import__("datetime").datetime.min.time())
        end_dt = __import__("datetime").datetime.combine(end, __import__("datetime").datetime.max.time()).replace(microsecond=0)
        square_sales = period_costing(db, start_dt, end_dt)["period_sales"]
        lines = flatten_pnl(SAMPLE_PNL)
        board = finance_board(db, start, end, qb_lines=lines)
        assert board["net_sales"] == square_sales
        assert board["qb_income"] == Decimal("88000.00")
        assert board["net_sales"] != board["qb_income"]
        assert board["cogs"] == Decimal("16300.00")
        assert board["labor"] == Decimal("20000.00")
        assert "unpaid" not in str(board).lower()
    finally:
        db.close()


def test_qb_callback_uses_hostname_when_oauth_url_is_set(monkeypatch):
    from app import config, quickbooks

    monkeypatch.setattr(config.settings, "resto_oauth_url", "http://lerouxfamily.example.ts.net:8088")
    assert quickbooks.qb_callback_url() == "http://lerouxfamily.example.ts.net:8088/connect/quickbooks/callback"


def test_connect_page_shows_quickbooks_key_fields():
    with TestClient(app) as client:
        page = client.get("/connect")
        assert page.status_code == 200
        assert 'name="application_id"' in page.text
        assert 'action="/connect/quickbooks/app"' in page.text
        assert "Save QuickBooks keys" in page.text
        assert "Sign in with Intuit" in page.text or 'action="/connect/quickbooks/app"' in page.text


def test_finance_page_has_no_ap_workflow():
    with TestClient(app) as client:
        page = client.get("/finance")
        assert page.status_code == 200
        text = unescape(page.text)
        assert "P&L" in text or "P&amp;L" in page.text
        assert "Net sales" in text
        assert "unpaid bills" not in text.lower()
        assert "due date" not in text.lower()
        assert "Connect QuickBooks" in text or "Open Connections" in text
        assert f"{date.today().year}-01-01" in text
        assert 'href="/finance?period=ytd&view=overview" class="on"' in page.text
        assert "Sales" in text
        assert "Vendors" in text
        sales = client.get("/finance?view=sales")
        assert sales.status_code == 200
        assert "Top 20 items" in unescape(sales.text)
        assert "Gift cards" in unescape(sales.text)
        assert "Top 10 categories" in unescape(sales.text)
        assert "Last year same dates" in unescape(sales.text)
        assert "unpaid bills" not in sales.text.lower()
        vendors = client.get("/finance?view=vendors")
        assert vendors.status_code == 200
        assert "Vendors" in unescape(vendors.text)
        assert "unpaid bills" not in vendors.text.lower()


def test_expense_group_sorts_miscategorized_food_bills():
    assert expense_group("FPL Bonita Springs", "", "utility") == "utilities"
    assert expense_group("biBERK", "", "food") == "insurance"
    assert expense_group("Sam's Club", "", "food") == "cogs_food"
    assert expense_group("Parts Town, LLC", "", "food") == "repairs"
    assert expense_group("Tuff Shed", "", "food") == "occupancy"
    assert expense_group("Vestis", "", "food") == "linen"
    assert expense_group("PG Fine Wines", "", "wine") == "cogs_wine"
    assert expense_group("Survey Cafe (Internal)", "sams-club-2026-02-13-800000018839235", "food") == "cogs_food"
    assert expense_group("Survey Cafe (Internal)", "valentine days menu survey cafe", "food") == "marketing"
    assert expense_group("Survey Cafe (Internal)", "Proof for Order Item #2039451", "food") == "marketing"
    assert expense_group("", "Receipt $324.83 needs review", "food") == "uncategorized"
    assert expense_group("Estiva Collection", "Not an invoice - Samples", "food") == "skip"
    assert expense_group("VistaServ", "VistaServ 2026-08-21", "food") == "uncategorized"


def _file_bill(db, name: str, total: str, invoice_type: str = "food", title: str = "", day: date | None = None) -> None:
    supplier = db.query(Supplier).filter(Supplier.name == name).first()
    if supplier is None:
        supplier = Supplier(name=name, category=invoice_type, default_invoice_type=invoice_type)
        db.add(supplier)
        db.flush()
    db.add(
        Invoice(
            supplier_id=supplier.id,
            issued_on=day or date(date.today().year, 1, 15),
            total=Decimal(total),
            invoice_type=invoice_type,
            title=title or name,
        )
    )
    db.commit()


def test_year_board_uses_recategorized_invoices_not_sandbox_pnl():
    db = SessionLocal()
    try:
        year = date.today().year
        start, end = date(year, 1, 1), date(year, 1, 31)
        mark_connected(db, "quickbooks", "sandbox-token", environment="sandbox", company="Sandbox Company US 42d3")
        _file_bill(db, "Sam's Club", "100.00")
        _file_bill(db, "Parts Town, LLC", "400.00")
        _file_bill(db, "biBERK", "50.00")
        _file_bill(db, "VistaServ", "20.00", title="VistaServ leftover")
        board = finance_board(db, start, end)
        assert board["sandbox"] is True
        assert board["fetched"] == "sandbox-ignored"
        assert board["cogs_source"] == "paperless"
        assert board["expense_source"] == "paperless"
        assert board["cogs"] == Decimal("100.00")
        assert board["cogs_food"] == Decimal("100.00")
        assert board["qb_income"] == Decimal("0")
        assert any(row["key"] == "repairs" and row["amount"] == Decimal("400.00") for row in board["detail"])
        assert any(row["key"] == "insurance" and row["amount"] == Decimal("50.00") for row in board["detail"])
        assert board["uncategorized_total"] == Decimal("20.00")
        assert board["uncategorized"][0]["name"] == "VistaServ"
        assert board["charts"]["spend"]
        assert any(row["name"] == "Parts Town, LLC" for row in board["vendors"])
        assert "unpaid" not in str(board).lower()
    finally:
        db.close()


def test_vendor_rows_keep_recategorized_groups():
    rows = vendor_rows(
        [
            {"name": "Sam's Club", "group": "cogs_food", "amount": Decimal("100")},
            {"name": "Parts Town, LLC", "group": "repairs", "amount": Decimal("400")},
        ]
    )
    assert rows[0]["name"] == "Parts Town, LLC"
    assert rows[0]["label"] == "Repairs"
    assert rows[1]["pct"] == Decimal("20.00")


def test_finance_period_defaults_to_year():
    kind, start, end = finance_period()
    today = date.today()
    assert kind == "ytd"
    assert start == date(today.year, 1, 1)
    assert end == today


def test_quickbooks_oauth_round_trip():
    with patch("app.connect_routes.httpx.Client", QbClient), patch("app.quickbooks.httpx.Client", QbClient):
        with TestClient(app) as client:
            save = client.post(
                "/connect/quickbooks/app",
                data={"application_id": "qb-client", "application_secret": "qb-secret", "environment": "sandbox"},
                follow_redirects=True,
            )
            assert save.status_code == 200
            start = client.get("/connect/quickbooks", follow_redirects=False)
            assert start.status_code == 302
            location = start.headers["location"]
            assert "appcenter.intuit.com" in location
            assert "com.intuit.quickbooks.accounting" in location
            state = dict(part.split("=", 1) for part in location.split("?")[1].split("&") if "=" in part)["state"]
            done = client.get(
                f"/connect/quickbooks/callback?code=from-intuit&state={state}&realmId=123456",
                follow_redirects=True,
            )
            assert "QuickBooks is connected" in unescape(done.text)
