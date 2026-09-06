from fastapi.testclient import TestClient

from app.main import app


def test_home_is_one_page_for_vitals_fleet_library_and_files():
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert "Orbit" in text
        assert 'id="vitals"' in text
        assert 'id="fleet"' in text
        assert 'id="library"' in text
        assert 'id="files"' in text
        assert "CPU" in text
        assert "Memory" in text
        assert 'id="mkdir-name"' in text
        assert "Films" in text
        assert "Series" in text
        assert "Grabs" in text
        assert "media" not in text.lower() or "without calling it" in text
        missing = client.get("/nope", follow_redirects=False)
        assert missing.status_code == 303
        assert missing.headers["location"] == "/"
