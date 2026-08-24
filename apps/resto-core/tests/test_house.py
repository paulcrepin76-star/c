from fastapi.testclient import TestClient

from app.db import SessionLocal
from datetime import UTC, datetime, timedelta

from app.house import find_fridge, fridge_chart, house_board, house_series, record_reading
from app.main import app


def test_house_page_lists_cafe_coolers():
    with TestClient(app) as client:
        page = client.get("/house")
        assert page.status_code == 200
        assert "Walk-in cooler" in page.text
        assert 'href="/house/walk-in-cooler"' in page.text
        assert "Walk-in freezer" in page.text
        assert "Home Assistant" in page.text
        assert "Fridges" in page.text
        cameras = client.get("/house/cameras")
        assert cameras.status_code == 200
        assert "Frigate" in cameras.text
        assert "Cameras" in cameras.text
        assert 'href="https://100.116.48.120:8971"' in cameras.text
        assert "/frigate/api/kitchen/latest.jpg" in cameras.text
        assert "No live frames" in cameras.text
        home = client.get("/")
        assert 'href="/house"' in home.text
        assert 'href="/house/cameras"' in home.text


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


def test_wine_cellar_and_line_cooler_are_not_on_the_fridge_board():
    with TestClient(app) as client:
        page = client.get("/house")
        assert "Line cooler" not in page.text
        assert "Wine cellar" not in page.text
        missing = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "wine-cellar", "temp_f": 54.6, "source": "yolink"},
        )
        assert missing.status_code == 404
        ok = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "walk-in-cooler", "temp_f": 37.2, "humidity": 62.0, "source": "yolink"},
        )
        assert ok.status_code == 200
        board = house_board(SessionLocal())
        slugs = [card["fridge"].slug for card in board["fridges"]]
        assert "wine-cellar" not in slugs
        assert "line-cooler" not in slugs
        walk = next(card for card in board["fridges"] if card["fridge"].slug == "walk-in-cooler")
        assert float(walk["humidity"]) == 62.0


def test_yolink_device_names_fill_the_right_tiles():
    with TestClient(app) as client:
        walk = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "walkin-cooler", "temp_f": 37.0, "source": "yolink"},
        )
        prep = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "prep-fridge", "temp_f": 36.4, "source": "yolink"},
        )
        salad = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "salad-fridge", "temp_f": 38.1, "source": "yolink"},
        )
        assert walk.status_code == 200 and walk.json()["fridge"] == "Walk-in cooler"
        assert prep.status_code == 200 and prep.json()["fridge"] == "Prep fridge"
        assert salad.status_code == 200 and salad.json()["fridge"] == "Salad fridge"
        page = client.get("/house")
        assert "Dessert fridge" in page.text
        assert "Soda fridge" in page.text
        assert "Coffee station" in page.text


def test_fridge_chart_page_shows_swing():
    db = SessionLocal()
    fridge = find_fridge(db, slug="walk-in-cooler")
    now = datetime.now(UTC).replace(tzinfo=None)
    record_reading(db, fridge, temp_f=36.0, source="test", recorded_at=now - timedelta(hours=3))
    record_reading(db, fridge, temp_f=39.4, source="test", recorded_at=now - timedelta(hours=1))
    chart = fridge_chart(db, fridge, hours=24)
    assert chart["low"] == 36.0
    assert chart["high"] == 39.4
    assert chart["swing"] == 3.4
    db.close()
    with TestClient(app) as client:
        page = client.get("/house/walk-in-cooler")
        assert page.status_code == 200
        assert 'id="fridge-chart"' in page.text
        assert "Swing" in page.text
        assert "3.4°F" in page.text
        assert "No live frames from Frigate" in page.text
        missing = client.get("/house/not-a-fridge", follow_redirects=False)
        assert missing.status_code == 303


def test_frigate_proxy_returns_502_when_down(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "frigate_internal_url", "http://127.0.0.1:9")
    with TestClient(app) as client:
        dead = client.get("/frigate/api/kitchen/latest.jpg")
        assert dead.status_code == 502
        kept = __import__("app.house", fromlist=["safe_http_url"]).safe_http_url("/frigate/api/kitchen/latest.jpg")
        assert kept.startswith("/frigate/")


def test_celsius_converts_and_matches_slug():
    db = SessionLocal()
    fridge = find_fridge(db, slug="prep-cooler")
    assert fridge is not None
    row = record_reading(db, fridge, temp_f=__import__("app.house", fromlist=["to_fahrenheit"]).to_fahrenheit(temp_c=3), source="test")
    assert 36 <= float(row.temp_f) <= 38
    db.close()
