from fastapi.testclient import TestClient

from app.main import app


def test_core_pages_render_demo_wines():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Wines on list" in home.text
        assert 'href="/connect"' in home.text
        assert 'href="/finance"' in home.text
        assert 'href="/invoices/scan"' in home.text
        assert 'href="/house"' in home.text
        assert 'id="house-chart"' in home.text
        assert "Net sales" in home.text
        assert "Temperature" in home.text
        assert "Cameras" in home.text
        inventory = client.get("/inventory")
        assert inventory.status_code == 200
        assert "Sauvignon Blanc" in inventory.text
        assert "Counted bottles" not in inventory.text
        purchasing = client.get("/purchasing")
        assert purchasing.status_code == 200
        assert "Purchasing" in purchasing.text
        assert "Best price" in purchasing.text
        assert "1 month" in purchasing.text
        assert "class=\"compare\"" in purchasing.text or "compare-wrap" in purchasing.text
        connect = client.get("/connect")
        assert connect.status_code == 200
        assert "Connect Square" in connect.text
        finance = client.get("/finance")
        assert finance.status_code == 200
        assert "Net sales" in finance.text
        wines = client.get("/wines")
        assert wines.status_code == 200
        assert "Sauvignon Blanc" in wines.text
        costing = client.get("/costing")
        assert costing.status_code == 200
        summary = client.get("/api/costing/summary", headers={"X-API-Key": "test"})
        assert summary.status_code == 200
        assert "wine" in summary.json()["groups"]


def test_home_is_one_desk_for_sales_bills_and_house():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Home" in home.text
        assert "Needs you" in home.text
        assert "Connect Square so sales land here" in home.text
        assert 'href="/labor"' in home.text
        assert 'href="/documents"' in home.text
        assert 'href="/intelligence"' in home.text
        assert "unpaid bills" not in home.text.lower()
        assert "accounts payable" not in home.text.lower()
        redirect = client.get("/dashboard", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/"
        labor = client.get("/labor")
        assert labor.status_code == 200
        assert "will not invent labor" in labor.text.lower()
        documents = client.get("/documents")
        assert documents.status_code == 200
        assert "Paperless" in documents.text
        assert 'href="/invoices/scan"' in documents.text
        intelligence = client.get("/intelligence")
        assert intelligence.status_code == 200
        assert "Intelligence" in intelligence.text
        assert "overnight" in intelligence.text.lower()


def test_dashboard_series_includes_seed_sales():
    from datetime import UTC, datetime, timedelta

    from app.db import SessionLocal
    from app.services import daily_activity, dashboard_charts, period_costing

    db = SessionLocal()
    try:
        end = datetime.now(UTC).replace(tzinfo=None)
        start = end - timedelta(days=90)
        activity = daily_activity(db, start, end)
        costing = period_costing(db, start, end)
        charts = dashboard_charts(costing, activity)
        assert len(activity["labels"]) >= 7
        assert sum(activity["sales"]) > 0
        assert charts["mix"]
        assert charts["theoretical_pct"] >= 0
    finally:
        db.close()
