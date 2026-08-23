from fastapi.testclient import TestClient

from app.db import SessionLocal
from datetime import UTC, datetime, timedelta

from app.house import find_fridge, house_board, house_series, record_reading
from app.main import app


def test_house_page_lists_cafe_coolers():
    with TestClient(app) as client:
        page = client.get("/house")
        assert page.status_code == 200
        assert "Walk-in cooler" in page.text
        assert "Walk-in freezer" in page.text
        assert "Home Assistant" in page.text
        assert "Frigate" in page.text
        home = client.get("/")
        assert 'href="/house"' in home.text


def test_fridge_reading_api_and_alert():
    with TestClient(app) as client:
        ok = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"fridge": "Walk-in cooler", "temp_f": 51.0, "source": "test"},
        )
        assert ok.status_code == 200
        assert ok.json()["temp_f"] == 51.0
        board = house_board(SessionLocal())
        walk = next(card for card in board["fridges"] if card["fridge"].slug == "walk-in-cooler")
        assert walk["status"] == "alert"
        payload = client.get("/api/house", headers={"X-API-Key": "test"})
        assert payload.status_code == 200
        assert payload.json()["alerts"] >= 1


def test_house_series_has_temperature_and_camera_lines():
    db = SessionLocal()
    fridge = find_fridge(db, slug="walk-in-cooler")
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=7)
    record_reading(db, fridge, temp_f=37.2, source="test", recorded_at=end - timedelta(hours=2))
    series = house_series(db, start, end, live_cameras=2)
    assert series["labels"]
    assert any(value == 37.2 for value in series["temperature"] if value is not None)
    assert series["cameras"][-1] == 2
    db.close()


def test_celsius_converts_and_matches_slug():
    db = SessionLocal()
    fridge = find_fridge(db, slug="prep-cooler")
    assert fridge is not None
    row = record_reading(db, fridge, temp_f=__import__("app.house", fromlist=["to_fahrenheit"]).to_fahrenheit(temp_c=3), source="test")
    assert 36 <= float(row.temp_f) <= 38
    db.close()
