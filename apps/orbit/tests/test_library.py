from fastapi.testclient import TestClient

from app.library import snapshot
from app.main import app


def test_library_is_not_named_media():
    data = snapshot()
    labels = {data["films"]["label"], data["series"]["label"], data["grabs"]["label"], data["screen"]["label"]}
    assert labels == {"Films", "Series", "Grabs", "Screen"}
    assert data["films"]["files"] >= 1 or data["films"]["exists"]
    ids = {app["id"] for app in data["apps"]}
    assert {"radarr", "sonarr", "qbittorrent", "jellyfin"} <= ids
    for app in data["apps"]:
        assert app["status"] == "unlinked"


def test_library_api():
    with TestClient(app) as client:
        res = client.get("/api/library")
        assert res.status_code == 200
        body = res.json()
        assert "films" in body
        assert "recent" in body
        blob = str(body).lower()
        assert "sonarr" in blob or "series" in blob
