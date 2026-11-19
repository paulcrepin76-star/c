import json

import httpx

from app.hours import any_day_open, empty_hours, google_regular_hours
from app.menu_extract import parse_menu_text
from app.postiz import map_remote_state


def test_login_and_overview_have_no_invented_activity(owner):
    denied = owner.post("/api/logout")
    assert denied.status_code == 200
    blocked = owner.get("/api/overview")
    assert blocked.status_code == 401
    owner.post("/api/login", json={"email": "owner@survey.test", "password": "nope"})
    owner.post("/api/login", json={"email": "owner@survey.test", "password": "correct-horse"})
    overview = owner.get("/api/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["customer_activity"] is None
    assert body["ad_spend"] == []
    assert body["counts"]["posts_in_progress"] == 0
    statuses = {row["service"]: row for row in body["statuses"]}
    assert statuses["n8n"]["reachable"] is False
    assert statuses["postgres"]["reachable"] is True


def test_yelp_push_stays_manual_and_google_confirms_only_on_success(owner, monkeypatch):
    yelp = owner.post("/api/profiles/yelp/push")
    assert yelp.status_code == 200
    assert yelp.json()["sync_state"] == "manual"
    assert yelp.json()["confirmed_at"] is None

    calls = {}

    class Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def patch(self, url, params=None, headers=None, json=None):
            calls["json"] = json
            calls["mask"] = params["updateMask"]
            status = calls.get("status", 403)
            return httpx.Response(status, json={"name": "locations/1", "error": {"message": "forbidden"}})

    monkeypatch.setattr("app.listings.httpx.Client", Dummy)
    owner.put(
        "/api/settings/secrets",
        json={"name": "google_access_token", "value": "token"},
    )
    owner.put("/api/settings/secrets", json={"name": "google_location_id", "value": "locations/99"})
    owner.put(
        "/api/profiles/google",
        json={
            "location_name": "Survey Café",
            "description": "Spanish kitchen",
            "phone": "",
            "website": "",
            "hours": empty_hours(),
            "holiday_hours": [],
            "announcement": "Paella night",
        },
    )
    rejected = owner.post("/api/profiles/google/push")
    assert rejected.status_code == 200
    assert rejected.json()["sync_state"] == "rejected"
    assert rejected.json()["confirmed_at"] is None
    assert "regularHours" not in calls["json"]
    assert "announcement" not in calls["json"]
    assert "title" in calls["mask"]

    calls["status"] = 200
    confirmed = owner.post("/api/profiles/google/push")
    assert confirmed.json()["sync_state"] == "confirmed"
    assert confirmed.json()["confirmed_at"]
    assert "Google accepted" in confirmed.json()["sync_detail"]
    assert "announcement" in confirmed.json()["sync_detail"].lower() or "Announcement" in confirmed.json()["sync_detail"]


def test_menu_parser_and_upload(owner):
    parsed = parse_menu_text("Paella Valenciana | saffron rice | 28\nGarlic shrimp - $16.50\nnot a price line\n")
    assert parsed[0]["name"] == "Paella Valenciana"
    assert parsed[0]["price_cents"] == 2800
    assert parsed[1]["price_cents"] == 1650
    assert len(parsed) == 2
    response = owner.post(
        "/api/menu/documents",
        files={"file": ("menu.txt", b"Tortilla | potato | 12\n", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "extracted"
    items = owner.get("/api/menu/items").json()["items"]
    assert items[0]["approved"] is False
    assert items[0]["price_cents"] == 1200
    approved = owner.patch(f"/api/menu/items/{items[0]['id']}", json={"approved": True, "category": "Tapas"})
    assert approved.json()["approved"] is True


def test_post_is_not_marked_published_without_postiz(owner, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("Postiz should not be called for Instagram without media")

    monkeypatch.setattr("app.postiz.request", explode)
    created = owner.post(
        "/api/posts",
        json={"body": "Tonight", "channels": [{"integration_id": "ig1", "provider": "instagram"}], "scheduled_for": ""},
    )
    refused = owner.post(f"/api/posts/{created.json()['id']}/submit?mode=now")
    assert refused.status_code == 409
    assert created.json()["status"] == "draft"

    monkeypatch.setattr(
        "app.postiz.request",
        lambda *args, **kwargs: __import__("app.remote", fromlist=["Remote"]).Remote(False, 0, None, "Postiz public API key is not saved"),
    )
    facebook = owner.post(
        "/api/posts",
        json={"body": "Hello", "channels": [{"integration_id": "fb1", "provider": "facebook"}], "scheduled_for": ""},
    )
    submitted = owner.post(f"/api/posts/{facebook.json()['id']}/submit?mode=now")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "draft"
    assert submitted.json()["release_url"] == ""
    assert "API key" in submitted.json()["detail"]
    assert map_remote_state("QUEUE") == "submitted"
    assert map_remote_state("PUBLISHED") == "published"


def test_review_reply_requires_support_and_approval(owner, monkeypatch):
    yelp = owner.post(
        "/api/reviews",
        json={"platform": "yelp", "author": "Sam", "rating": 4, "body": "Lovely rice", "reviewed_at": ""},
    ).json()
    owner.post(f"/api/reviews/{yelp['id']}/draft")
    owner.post(f"/api/reviews/{yelp['id']}/approval", json={"approval": "approved"})
    sent = owner.post(f"/api/reviews/{yelp['id']}/send")
    assert sent.json()["publish_state"] == "unavailable"
    assert sent.json()["draft_source"] == "template"

    def boom(*args, **kwargs):
        raise AssertionError("Google should not be called before approval")

    monkeypatch.setattr("app.listings.reply_google_review", boom)
    google = owner.post(
        "/api/reviews",
        json={
            "platform": "google",
            "author": "Ana",
            "rating": 5,
            "body": "Great paella",
            "reviewed_at": "",
        },
    ).json()
    early = owner.post(f"/api/reviews/{google['id']}/send")
    assert early.status_code == 409


def test_event_queue_does_not_publish_and_n8n_key_is_required(owner):
    event = owner.post(
        "/api/events",
        json={"name": "Paella Night", "kind": "dinner", "starts_at": "2026-12-01T18:00:00", "description": "Two seatings"},
    ).json()
    queued = owner.post(f"/api/events/{event['id']}/queue")
    assert queued.json()["published"] is False
    assert queued.json()["post"]["status"] == "draft"
    assert queued.json()["campaign"]["status"] == "local"
    anon = owner.post("/api/logout")
    assert anon.status_code == 200
    missing = owner.post("/api/n8n/events/announce", json={"name": "Private dinner", "starts_at": "2026-12-02T19:00:00"})
    assert missing.status_code == 401
    announced = owner.post(
        "/api/n8n/events/announce",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Private dinner", "starts_at": "2026-12-02T19:00:00", "description": "Buyout"},
    )
    assert announced.status_code == 200
    assert announced.json()["published"] is False


def test_export_leaves_secrets_out(owner):
    owner.put("/api/settings/secrets", json={"name": "mautic_password", "value": "super-secret-value"})
    exported = json.dumps(owner.get("/api/admin/export").json())
    assert "super-secret-value" not in exported
    assert "secrets_included" in exported
    settings = owner.get("/api/settings").json()
    password = next(field for field in settings["fields"] if field["name"] == "mautic_password")
    assert password["configured"] is True
    assert password["value"] == ""


def test_closed_week_is_not_a_google_hours_payload():
    assert google_regular_hours(empty_hours()) is None
    assert any_day_open(empty_hours()) is False


def test_marketing_compose_does_not_touch_n8n_or_set_memory_limits():
    text = open("/workspace/compose.marketing.yml", encoding="utf-8").read()
    assert 'profiles: ["marketing"]' in text
    assert "mautic/mautic:5-apache" in text
    assert "ghcr.io/gitroomhq/postiz-app:latest" in text
    assert "mem_limit" not in text
    assert "resto-n8n" not in text
    assert "temporalio/auto-setup:1.28.1" in text
    main = open("/workspace/compose.yml", encoding="utf-8").read()
    assert "mautic/mautic" not in main
    assert "postiz-app" not in main
