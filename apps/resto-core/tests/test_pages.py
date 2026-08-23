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
