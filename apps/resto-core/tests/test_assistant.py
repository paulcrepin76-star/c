import httpx
from fastapi.testclient import TestClient

from app import assistant
from app.config import settings
from app.main import app

BOT_HEALTH = {
    "ok": True,
    "app": "grok-bot",
    "model": "grok-4.6",
    "grok": True,
    "telegram": {"enabled": True, "running": True, "paired_chats": 1, "messages": 4, "last_error": ""},
    "docker": True,
    "confirm_before_changes": True,
}


def _bot(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(settings, "bot_url", "http://grok-bot:8090")
    monkeypatch.setattr(
        assistant.httpx,
        "Client",
        lambda *_a, **_kw: real_client(transport=httpx.MockTransport(handler)),
    )


def test_assistant_page_explains_how_to_pair_a_phone(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=BOT_HEALTH)

    _bot(monkeypatch, handler)
    with TestClient(app) as client:
        page = client.get("/assistant")
    assert page.status_code == 200
    assert "Assistant" in page.text
    assert "BotFather" in page.text
    assert "TELEGRAM_ALLOWED_CHAT_IDS" in page.text
    assert "grok-4.6" in page.text
    assert "Listening" in page.text
    assert 'id="chat-form"' in page.text


def test_the_menu_links_to_the_assistant():
    with TestClient(app) as client:
        home = client.get("/")
    assert 'href="/assistant"' in home.text


def test_the_page_says_when_the_bot_container_is_down():
    with TestClient(app) as client:
        page = client.get("/assistant")
    assert page.status_code == 200
    assert "not answering" in page.text
    assert "docker compose up -d grok-bot" in page.text


def test_sending_a_message_relays_the_bots_answer(monkeypatch):
    seen = {}

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json=BOT_HEALTH)
        seen["body"] = request.read().decode()
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"reply": "Today is $640 on 41 tickets."})

    _bot(monkeypatch, handler)
    with TestClient(app) as client:
        response = client.post("/assistant/send", json={"message": "how are things"})
    assert response.json() == {"ok": True, "reply": "Today is $640 on 41 tickets."}
    assert "how are things" in seen["body"]
    assert seen["key"] == settings.resto_api_key


def test_a_dead_bot_becomes_a_readable_sentence(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _bot(monkeypatch, handler)
    with TestClient(app) as client:
        response = client.post("/assistant/send", json={"message": "status"})
    body = response.json()
    assert body["ok"] is False
    assert "did not answer" in body["reply"]


def test_no_bot_url_is_explained_not_hidden():
    with TestClient(app) as client:
        body = client.post("/assistant/send", json={"message": "status"}).json()
    assert body["ok"] is False
    assert "BOT_URL" in body["reply"]


def test_status_endpoint_answers_how_are_things():
    with TestClient(app) as client:
        unauthorised = client.get("/api/status")
        assert unauthorised.status_code == 401
        body = client.get("/api/status", headers={"X-API-Key": "test"}).json()
    assert body["restaurant"] == "Survey Cafe"
    assert set(body["sales"]) == {"today", "month_to_date", "year_to_date", "tickets_today", "avg_ticket_today"}
    assert set(body["month"]) >= {"net_sales", "food_cost_pct", "wine_cost_pct", "operating_profit"}
    assert body["fridges"]["total"] >= 1
    assert isinstance(body["needs_you"], list)
    assert body["data_confidence"] in ("complete", "partial", "unreliable")
    assert "square" in body["connections"]
