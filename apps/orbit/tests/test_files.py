from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path("/tmp/orbit-pytest-files")


def test_roots_and_listing():
    with TestClient(app) as client:
        roots = client.get("/api/files/roots").json()["roots"]
        labels = {row["id"] for row in roots}
        assert "Documents" in labels
        assert "Library" in labels
        listing = client.get("/api/files", params={"root": "Documents"})
        assert listing.status_code == 200
        names = {item["name"] for item in listing.json()["items"]}
        assert "note.txt" in names


def test_rejects_path_traversal():
    with TestClient(app) as client:
        res = client.get("/api/files", params={"root": "Documents", "path": "../library"})
        assert res.status_code == 400


def test_mkdir_upload_download_delete(tmp_path=None):
    with TestClient(app) as client:
        made = client.post("/api/files/mkdir", data={"root": "Documents", "path": "", "name": "inbox"})
        assert made.status_code == 200
        names = {item["name"] for item in made.json()["items"]}
        assert "inbox" in names
        upload = client.post(
            "/api/files/upload",
            data={"root": "Documents", "path": "inbox"},
            files={"file": ("clip.txt", b"hello orbit", "text/plain")},
        )
        assert upload.status_code == 200
        down = client.get("/api/files/download", params={"root": "Documents", "path": "inbox/clip.txt"})
        assert down.status_code == 200
        assert down.content == b"hello orbit"
        gone = client.post("/api/files/delete", data={"root": "Documents", "path": "inbox/clip.txt"})
        assert gone.status_code == 200
        left = {item["name"] for item in gone.json()["items"]}
        assert "clip.txt" not in left
        client.post("/api/files/delete", data={"root": "Documents", "path": "inbox"})


def test_unknown_root_is_404():
    with TestClient(app) as client:
        res = client.get("/api/files", params={"root": "Nope"})
        assert res.status_code == 404
