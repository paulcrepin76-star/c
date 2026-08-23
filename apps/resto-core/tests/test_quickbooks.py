from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.quickbooks import finance_board, flatten_pnl, map_account
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
