import json

from app import brain, state, tools
from app.settings import settings

STATUS = {
    "sales": {"today": 1240.5, "month_to_date": 28400.0, "tickets_today": 63, "avg_ticket_today": 19.7},
    "month": {"food_cost_pct": 31.4, "wine_cost_pct": 26.1, "operating_profit": 4200.0},
    "fridges": {"alerts": 1, "online": 7, "total": 7, "out_of_range": [{"name": "Prep fridge", "temp_f": 46.2, "status": "alert"}]},
    "wine_below_par": ["Sancerre"],
    "needs_you": ["3 bills need a category"],
}


def test_status_question_answers_without_a_model(monkeypatch):
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    reply = brain.answer("how are things", chat="test")
    assert "$1,240" in reply
    assert "63 tickets" in reply
    assert "food 31.4%" in reply
    assert "Prep fridge 46.2F" in reply
    assert "3 bills need a category" in reply


def test_a_restart_waits_for_yes(monkeypatch):
    calls = []
    monkeypatch.setitem(
        tools.HANDLERS,
        "restart_app",
        lambda app: calls.append(app) or {"ok": True, "app": app, "action": "restart", "state": "running", "status": "Up 1 second"},
    )

    asked = brain.answer("restart n8n", chat="test")
    assert "about to restart n8n" in asked.lower()
    assert calls == []

    done = brain.answer("yes", chat="test")
    assert calls == ["n8n"]
    assert "Restarted n8n. It is running." in done


def test_no_means_nothing_runs(monkeypatch):
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: {"ok": True})
    brain.answer("restart n8n", chat="test")
    reply = brain.answer("no", chat="test")
    assert "Nothing changed" in reply
    assert state.get_pending("test") is None


def test_a_new_question_drops_the_pending_action(monkeypatch):
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: {"ok": True})
    brain.answer("restart n8n", chat="test")
    brain.answer("status", chat="test")
    assert state.get_pending("test") is None


def test_reads_run_straight_away(monkeypatch):
    monkeypatch.setitem(tools.HANDLERS, "app_logs", lambda app, lines=40: {"app": "resto-n8n", "state": "running", "logs": "ready on 5678"})
    reply = brain.answer("logs n8n", chat="test")
    assert "ready on 5678" in reply
    assert state.get_pending("test") is None


def test_every_change_lands_in_the_audit_log(monkeypatch):
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: {"ok": True, "app": app, "action": "restart", "state": "running", "status": "Up"})
    brain.answer("restart n8n", chat="test")
    brain.answer("yes", chat="test")
    rows = state.recent_actions()
    assert rows[-1]["tool"] == "restart_app"
    assert rows[-1]["args"] == {"app": "n8n"}
    assert rows[-1]["ok"] is True


def test_confirm_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "require_confirm", False)
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: {"ok": True, "app": app, "action": "restart", "state": "running", "status": "Up"})
    reply = brain.answer("restart n8n", chat="test")
    assert "Restarted n8n. It is running." in reply


def test_help_lists_what_it_understands():
    assert "update" in brain.answer("help", chat="test")
    assert "sync" in brain.answer("/start", chat="test")


def test_without_a_key_free_text_gets_the_command_list():
    reply = brain.answer("tell me a joke about wine", chat="test")
    assert "xAI key" in reply


def _grok_reply(content="", calls=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": f"call{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for index, (name, args) in enumerate(calls)
        ]
    return message


def test_grok_calls_a_tool_then_answers_in_words(monkeypatch, mock_http):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    replies = [
        _grok_reply(calls=[("restaurant_status", {})]),
        _grok_reply("Today is $1,240 on 63 tickets. The prep fridge is warm at 46F."),
    ]
    sent = []

    def fake_complete(messages, tools=None, conversation=""):  # noqa: ARG001
        sent.append(messages)
        return replies.pop(0)

    monkeypatch.setattr(brain.grok, "complete", fake_complete)
    reply = brain.answer("how are things at the cafe today?", chat="test")
    assert "prep fridge is warm" in reply.lower()
    assert any(message.get("role") == "tool" for message in sent[-1])


def test_grok_asking_for_a_restart_still_waits_for_yes(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    ran = []
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: ran.append(app) or {"ok": True, "app": app, "action": "restart", "state": "running", "status": "Up"})
    monkeypatch.setattr(brain.grok, "complete", lambda *_a, **_k: _grok_reply(calls=[("restart_app", {"app": "n8n"})]))
    asked = brain.answer("n8n looks stuck, bounce it", chat="test")
    assert "Reply yes" in asked
    assert ran == []
    brain.answer("yes", chat="test")
    assert ran == ["n8n"]


def test_when_xai_is_down_plain_commands_still_work(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)

    def boom(*_a, **_k):
        raise brain.GrokError("xAI answered 503")

    monkeypatch.setattr(brain.grok, "complete", boom)
    reply = brain.answer("how are things looking right now?", chat="test")
    assert "xAI answered 503" in reply
    assert "$1,240" in reply


def test_a_short_command_never_reaches_the_model(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    ran = []
    monkeypatch.setitem(tools.HANDLERS, "restart_app", lambda app: ran.append(app) or {"ok": True, "app": app, "action": "restart", "state": "running"})

    def never(*_a, **_k):
        raise AssertionError("the model was asked about a plain command")

    monkeypatch.setattr(brain.grok, "complete", never)
    assert "Reply yes" in brain.answer("restart n8n", chat="test")
    brain.answer("yes", chat="test")
    assert ran == ["n8n"]


def test_a_sentence_still_goes_to_the_model(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(brain.grok, "complete", lambda *_a, **_k: _grok_reply("Grok answered."))
    assert brain.answer("n8n looks stuck, what do you think?", chat="test") == "Grok answered."


def test_an_empty_completion_falls_back_instead_of_dead_ending(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(tools.resto, "restaurant_status", lambda: STATUS)
    monkeypatch.setattr(brain.grok, "complete", lambda *_a, **_k: _grok_reply(""))
    assert "$1,240" in brain.answer("how are things looking tonight?", chat="test")


def test_an_empty_completion_on_free_text_says_what_to_try(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(brain.grok, "complete", lambda *_a, **_k: _grok_reply(""))
    reply = brain.answer("tell me something about the walk in cooler", chat="test")
    assert settings.grok_model in reply
    assert "plain command" in reply


def test_grok_history_survives_between_messages(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    monkeypatch.setattr(brain.grok, "complete", lambda *_a, **_k: _grok_reply("Sure."))
    brain.answer("hello", chat="test")
    turns = state.history("test")
    assert turns[0] == {"role": "user", "content": "hello"}
    assert turns[1] == {"role": "assistant", "content": "Sure."}
