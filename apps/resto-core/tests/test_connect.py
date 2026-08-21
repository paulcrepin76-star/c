from html import unescape
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    fail = False

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        if self.fail:
            return FakeResponse(401, {"detail": "nope"})
        if url.endswith("/api/auth/token"):
            return FakeResponse(200, {"access_token": "mealie-token"})
        if url.endswith("/api/token/"):
            return FakeResponse(200, {"token": "paper-token"})
        if "/oauth2/token" in url:
            return FakeResponse(200, {"access_token": "sq-access", "refresh_token": "sq-refresh", "merchant_id": "m1"})
        return FakeResponse(404, {})

    def get(self, url, **kwargs):
        if self.fail:
            return FakeResponse(401, {})
        if "/api/recipes" in url:
            return FakeResponse(200, {"items": []})
        if "/api/documents/" in url:
            return FakeResponse(200, {"results": []})
        if "/v2/locations" in url:
            return FakeResponse(200, {"locations": [{"id": "LOC1", "status": "ACTIVE", "merchant_id": "m1"}]})
        return FakeResponse(200, {})


def test_connect_page_is_the_login_door():
    with TestClient(app) as client:
        page = client.get("/connect")
        assert page.status_code == 200
        text = unescape(page.text)
        assert "Connect Square" in text
        assert "Connect Mealie" in text
        assert "Connect Paperless" in text
        assert "FPL Bonita Springs" in text
        assert "Chef's Warehouse" in text
        assert "The Greatest Spring Water" in text
        assert "Sam's Club" in text
        assert "Costco" in text
        assert "Gordon Food Service" in text
        setup = client.get("/setup", follow_redirects=False)
        assert setup.status_code == 303
        assert setup.headers["location"] == "/connect"


def test_mealie_and_paperless_login_then_square_token():
    with patch("app.connect_routes.httpx.Client", FakeClient):
        with TestClient(app) as client:
            mealie = client.post(
                "/connect/mealie",
                data={"username": "survey", "password": "secret"},
                follow_redirects=True,
            )
            assert mealie.status_code == 200
            assert "Mealie is connected" in mealie.text
            paper = client.post(
                "/connect/paperless",
                data={"username": "phsp", "password": "secret"},
                follow_redirects=True,
            )
            assert "Paperless is connected" in paper.text
            square = client.post(
                "/connect/square/token",
                data={"access_token": "Bearer sq-personal"},
                follow_redirects=True,
            )
            assert "Square is connected" in square.text


def test_square_oauth_round_trip():
    with patch("app.connect_routes.httpx.Client", FakeClient):
        with TestClient(app) as client:
            client.post(
                "/connect/square/app",
                data={"application_id": "sq0idp-app", "application_secret": "sq0csp-secret"},
                follow_redirects=True,
            )
            start = client.get("/connect/square", follow_redirects=False)
            assert start.status_code == 302
            location = start.headers["location"]
            assert "oauth2/authorize" in location
            state = dict(part.split("=", 1) for part in location.split("?")[1].split("&") if "=" in part)["state"]
            done = client.get(f"/connect/square/callback?code=from-square&state={state}", follow_redirects=True)
            assert "Square is connected" in done.text


def test_bad_mealie_login_does_not_store_a_token():
    FakeClient.fail = True
    try:
        with patch("app.connect_routes.httpx.Client", FakeClient):
            with TestClient(app) as client:
                page = client.post(
                    "/connect/mealie",
                    data={"username": "survey", "password": "wrong"},
                    follow_redirects=True,
                )
                assert "Mealie login failed" in page.text
                assert "Mealie is connected" not in page.text
    finally:
        FakeClient.fail = False


def test_sync_all_skips_until_connected():
    with TestClient(app) as client:
        response = client.post("/api/jobs/sync-all", headers={"X-API-Key": "test"})
        assert response.status_code == 200
        body = response.json()
        assert body["square"]["status"] == "skipped"
        assert body["mealie"]["status"] == "skipped"
        assert body["paperless"]["status"] == "skipped"


def test_vendor_connect_uses_the_same_login_you_already_have():
    with TestClient(app) as client:
        page = client.post(
            "/connect/vendor/fpl",
            data={"username": "surveycafedowntown@gmail.com", "account": "bonita-1"},
            follow_redirects=True,
        )
        assert page.status_code == 200
        assert "FPL Bonita Springs is connected" in unescape(page.text)
        warehouse = client.post(
            "/connect/vendor/chefs-warehouse",
            data={"username": "survey-cafe"},
            follow_redirects=True,
        )
        assert "Chef's Warehouse is connected" in unescape(warehouse.text)


