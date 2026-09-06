from fastapi.testclient import TestClient

from app import main, telegram, tools
from app.main import app
from app.settings import settings

STATUS = {
    "sales": {"today": 640.0, "month_to_date": 12000.0, "tickets_today": 41, "avg_ticket_today": 15.6},
    "month": {"food_cost_pct": 30.0, "wine_cost_pct": 25.0, "operating_profit": 900.0},
    "fridges": {"alerts": 0, "online": 7, "total": 7, "out_of_range": []},
    "needs_you": [],
}


def test_health_says_what_is_wired_up():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["ok"] is True
    assert body["app"] == "grok-bot"
    assert body["confirm_before_changes"] is True
    assert body["telegram"]["enabled"] is False


def test_chat_needs_the_api_key(monkeypatch):
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    with TestClient(app) as client:
        assert client.post("/chat", json={"message": "status"}).status_code == 401
        ok = client.post("/chat", json={"message": "status"}, headers={"X-API-Key": settings.resto_api_key})
    assert ok.status_code == 200
    assert "$640.00" in ok.json()["reply"]


def test_sms_answers_with_twiml(monkeypatch):
    monkeypatch.setattr(main, "answer", lambda text, chat="web": f"echo {text}")
    with TestClient(app) as client:
        response = client.post("/sms", data={"Body": "status", "From": "+15551234567"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Message>echo status</Message>" in response.text


def test_sms_from_a_stranger_is_turned_away(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "+15550000000")
    with TestClient(app) as client:
        response = client.post("/sms", data={"Body": "restart n8n", "From": "+15559999999"})
    assert "not paired" in response.text


def test_actions_log_is_behind_the_key():
    with TestClient(app) as client:
        assert client.get("/actions").status_code == 401
        assert client.get("/actions", headers={"X-API-Key": settings.resto_api_key}).status_code == 200


def test_an_unpaired_phone_is_told_its_chat_id():
    reply = telegram.channel.reply_to("998877", "status")
    assert "998877" in reply
    assert "TELEGRAM_ALLOWED_CHAT_IDS" in reply


def test_a_stranger_gets_nothing_useful(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "12345")
    assert "only answers" in telegram.channel.reply_to("998877", "restart n8n")


def test_a_paired_phone_reaches_the_brain(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "12345")
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    reply = telegram.channel.reply_to("12345", "status")
    assert "41 tickets" in reply


def test_long_replies_are_split_into_telegram_sized_chunks(monkeypatch):
    chunks = []
    monkeypatch.setattr(telegram.channel, "call", lambda method, payload, timeout=20.0: chunks.append(payload["text"]) or {})
    telegram.channel.send("1", "x" * (telegram.MAX_MESSAGE + 10))
    assert len(chunks) == 2
    assert len(chunks[0]) == telegram.MAX_MESSAGE


def test_one_update_becomes_one_reply(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "12345")
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    monkeypatch.setattr(telegram.channel, "call", lambda method, payload, timeout=20.0: sent.append((method, payload)) or {})
    telegram.channel.handle({"update_id": 1, "message": {"chat": {"id": 12345}, "text": "status"}})
    methods = [method for method, _ in sent]
    assert methods == ["sendChatAction", "sendMessage"]
    assert "41 tickets" in sent[-1][1]["text"]
