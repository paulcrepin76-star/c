import json

import httpx
import pytest

from app import grok
from app.settings import settings


def _reply(payload, status=200):
    def handler(request):
        handler.request = request
        return httpx.Response(status, json=payload)

    return handler


def test_no_key_is_a_clear_error():
    with pytest.raises(grok.GrokError, match="XAI_API_KEY"):
        grok.complete([{"role": "user", "content": "hi"}])


def test_a_normal_answer_comes_back_as_text(monkeypatch, mock_http):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    handler = _reply({"choices": [{"message": {"role": "assistant", "content": "All good."}}]})
    mock_http(grok, handler)
    message = grok.complete([{"role": "user", "content": "how are things"}], conversation="tg:42")
    assert grok.text_of(message) == "All good."
    assert handler.request.headers["authorization"] == "Bearer test-xai"
    assert handler.request.headers["x-grok-conv-id"] == "tg:42"
    body = json.loads(handler.request.content)
    assert body["model"] == settings.grok_model
    assert body["messages"][0]["content"] == "how are things"


def test_tools_are_offered_and_parsed_back(monkeypatch, mock_http):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    handler = _reply(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "call_1", "type": "function", "function": {"name": "app_logs", "arguments": '{"app": "n8n", "lines": 20}'}}
                        ],
                    }
                }
            ]
        }
    )
    mock_http(grok, handler)
    message = grok.complete([{"role": "user", "content": "why is n8n down"}], tools=[{"type": "function"}])
    calls = grok.tool_calls(message)
    assert calls == [{"id": "call_1", "name": "app_logs", "args": {"app": "n8n", "lines": 20}}]
    assert json.loads(handler.request.content)["tool_choice"] == "auto"


def test_broken_json_arguments_do_not_crash_the_bot(monkeypatch, mock_http):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    message = {"tool_calls": [{"id": "c", "type": "function", "function": {"name": "server_status", "arguments": "{oops"}}]}
    assert grok.tool_calls(message) == [{"id": "c", "name": "server_status", "args": {}}]


@pytest.mark.parametrize(
    ("status", "needle"),
    [(401, "rejected the key"), (429, "rate limiting"), (500, "answered 500")],
)
def test_http_errors_are_translated(monkeypatch, mock_http, status, needle):
    monkeypatch.setattr(settings, "xai_api_key", "test-xai")
    mock_http(grok, _reply({"error": "nope"}, status))
    with pytest.raises(grok.GrokError, match=needle):
        grok.complete([{"role": "user", "content": "hi"}])
