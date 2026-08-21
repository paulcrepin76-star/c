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
        assert "Net sales" in home.text
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
            assert "costing will catch them" in uploaded.text
    assert FakePaperless.posted
    assert FakePaperless.posted[0]["url"].endswith("/api/documents/post_document/")
    assert FakePaperless.posted[0]["data"]["title"] == "Costco"


class WorkflowClient:
    created = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        class Response:
            status_code = 200

            def json(self):
                return {"results": []}

            def raise_for_status(self):
                return None

        return Response()

    def post(self, url, **kwargs):
        WorkflowClient.created.append({"url": url, "json": kwargs.get("json")})

        class Response:
            status_code = 201
            text = ""

            def json(self):
                return {"id": 1, "name": "Resto cellar: new invoice"}

        return Response()


def test_sync_paperless_job_accepts_header_or_query_token():
    with TestClient(app) as client:
        assert client.post("/api/jobs/sync-paperless").status_code == 401
        first = client.post("/api/jobs/sync-paperless", headers={"X-API-Key": "test"})
        assert first.status_code == 200
        assert first.json()["status"] in ("ok", "skipped")
        second = client.post("/api/jobs/sync-paperless", headers={"X-API-Key": "test"})
        assert second.status_code == 200
        assert second.json().get("throttled") is True
        import app.paperless_hook as hook

        hook._last_sync = 0
        query = client.post("/api/jobs/sync-paperless?token=test")
        assert query.status_code == 200


def test_paperless_workflow_is_created_for_new_invoices():
    WorkflowClient.created = []
    db = SessionLocal()
    mark_connected(db, "paperless", "paper-token")
    from app.paperless_hook import ensure_paperless_sync_workflow

    with patch("app.paperless_hook.httpx.Client", WorkflowClient):
        result = ensure_paperless_sync_workflow(db)
    db.close()
    assert result["status"] == "ok"
    assert WorkflowClient.created
    payload = WorkflowClient.created[0]["json"]
    assert payload["name"] == "Resto cellar: new invoice"
    assert payload["actions"][0]["webhook"]["url"].endswith("/api/jobs/sync-paperless")

