from fastapi.testclient import TestClient

from app.catalog import match_service
from app.fleet import snapshot
from app.main import app


def test_fleet_uses_demo_without_docker_and_keeps_icons():
    data = snapshot()
    assert data["total"] >= 8
    assert data["running"] >= 1
    names = {item["title"] for item in data["items"]}
    assert "Cellar" in names
    assert "Home Assistant" in names
    assert "Frigate" in names
    assert "Series" in names
    assert "Films" in names
    groups = {group["name"] for group in data["groups"]}
    assert "Kitchen" in groups
    assert "House" in groups
    assert "Library" in groups


def test_catalog_matches_homepage_labels():
    meta = match_service(
        "random",
        "foo:latest",
        {
            "homepage.name": "Home Assistant",
            "homepage.group": "House",
            "homepage.icon": "home-assistant.png",
            "homepage.href": "http://100.116.48.120:8123",
        },
    )
    assert meta["title"] == "Home Assistant"
    assert meta["group"] == "House"
    assert meta["icon"] == "home"
    assert meta["href"].endswith(":8123")


def test_fleet_api():
    with TestClient(app) as client:
        res = client.get("/api/fleet")
        assert res.status_code == 200
        assert res.json()["items"]
