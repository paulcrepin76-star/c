from fastapi.testclient import TestClient

from app.main import app
from app.system import snapshot


def test_system_snapshot_has_vitals():
    data = snapshot()
    assert 0 <= data["cpu"]["percent"] <= 100
    assert data["cpu"]["cores"] >= 1
    assert 0 <= data["memory"]["percent"] <= 100
    assert data["memory"]["total"] > 0
    assert data["uptime"] >= 0
    assert data["disks"]


def test_system_api():
    with TestClient(app) as client:
        res = client.get("/api/system")
        assert res.status_code == 200
        body = res.json()
        assert "cpu" in body
        assert "memory" in body
        assert "uptime" in body
