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
        assert "Fridges" in page.text
        cameras = client.get("/house/cameras")
        assert cameras.status_code == 200
        assert "Frigate" in cameras.text
        assert "Cameras" in cameras.text
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


def test_wine_cellar_yolink_reading():
    with TestClient(app) as client:
        ok = client.post(
            "/api/house/readings",
            headers={"X-API-Key": "test"},
            json={"slug": "wine-cellar", "temp_f": 54.6, "humidity": 62.0, "source": "yolink"},
        )
        assert ok.status_code == 200
        assert ok.json()["fridge"] == "Wine cellar"
        assert ok.json()["temp_f"] == 54.6
        board = house_board(SessionLocal())
        wine = next(card for card in board["fridges"] if card["fridge"].slug == "wine-cellar")
        assert wine["status"] == "ok"
        assert float(wine["temp_f"]) == 54.6
        assert float(wine["humidity"]) == 62.0


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


def test_celsius_converts_and_matches_slug():
    db = SessionLocal()
    fridge = find_fridge(db, slug="prep-cooler")
    assert fridge is not None
    row = record_reading(db, fridge, temp_f=__import__("app.house", fromlist=["to_fahrenheit"]).to_fahrenheit(temp_c=3), source="test")
    assert 36 <= float(row.temp_f) <= 38
    db.close()
