from unittest.mock import patch

from fastapi.testclient import TestClient

from app.connections import mark_connected
from app.db import SessionLocal
from app.main import app


class FakePaperless:
    posted = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        FakePaperless.posted.append({"url": url, "data": kwargs.get("data"), "files": bool(kwargs.get("files"))})

        class Response:
            status_code = 200

            def json(self):
                return "task-1"

        return Response()


def test_pages_show_period_picker_and_scan_door():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Square sales" in home.text
        assert "/invoices/scan" in home.text
        assert "90 days" in home.text
        costing = client.get("/costing?days=365")
        assert costing.status_code == 200
        assert "Year" in costing.text
        invoices = client.get("/invoices")
        assert invoices.status_code == 200
        assert "Photograph invoices" in invoices.text
        scan = client.get("/invoices/scan")
        assert scan.status_code == 200
        assert "Photograph paper invoices" in scan.text
        match = client.get("/costing/match")
        assert match.status_code == 200
        assert "Auto-match now" in match.text


def test_iphone_scan_uploads_to_paperless():
    FakePaperless.posted = []
    db = SessionLocal()
    mark_connected(db, "paperless", "paper-token")
    db.close()
    with patch("app.web.httpx.Client", FakePaperless):
        with TestClient(app) as client:
            page = client.get("/invoices/scan")
            assert page.status_code == 200
            assert "Take one photo now" in page.text
            uploaded = client.post(
                "/invoices/scan",
                data={"vendor": "Costco"},
                files={"files": ("costco.jpg", b"fake-jpeg", "image/jpeg")},
                follow_redirects=True,
            )
            assert uploaded.status_code == 200
            assert "Sent 1 photo" in uploaded.text
    assert FakePaperless.posted
    assert FakePaperless.posted[0]["url"].endswith("/api/documents/post_document/")
    assert FakePaperless.posted[0]["data"]["title"] == "Costco"
