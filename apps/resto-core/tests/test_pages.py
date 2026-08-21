from fastapi.testclient import TestClient

from app.main import app


def test_core_pages_render_demo_wines():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Wine cost" in home.text
        assert 'href="/connect"' in home.text
        assert 'href="/invoices/scan"' in home.text
        connect = client.get("/connect")
        assert connect.status_code == 200
        assert "Connect Square" in connect.text
        wines = client.get("/wines")
        assert wines.status_code == 200
        assert "Sauvignon Blanc" in wines.text
        costing = client.get("/costing")
        assert costing.status_code == 200
        summary = client.get("/api/costing/summary", headers={"X-API-Key": "test"})
        assert summary.status_code == 200
        assert "wine" in summary.json()["groups"]
