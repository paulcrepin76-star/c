"""xAI Grok client. Chat Completions with function calling."""

from __future__ import annotations

import json

import httpx

from app.settings import settings


class GrokError(RuntimeError):
    pass


def _endpoint() -> str:
    return f"{settings.xai_base_url.rstrip('/')}/chat/completions"


def complete(messages: list[dict], tools: list[dict] | None = None, conversation: str = "") -> dict:
    """One round trip. Returns the assistant message dict."""
    if not settings.xai_api_key:
        raise GrokError("No xAI key. Set XAI_API_KEY in .env to let the bot answer in words.")
    payload: dict = {"model": settings.grok_model, "messages": messages, "temperature": 0.2}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {settings.xai_api_key}", "Content-Type": "application/json"}
    if conversation:
        # Keeps a conversation on one server so xAI can reuse the cached prompt.
        headers["x-grok-conv-id"] = conversation
    try:
        with httpx.Client(timeout=settings.grok_timeout) as client:
            response = client.post(_endpoint(), headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise GrokError(f"Could not reach {settings.xai_base_url}: {str(exc)[:160]}") from exc
    if response.status_code == 401:
        raise GrokError("xAI rejected the key. Check XAI_API_KEY at console.x.ai.")
    if response.status_code == 429:
        raise GrokError("xAI is rate limiting this key. Try again in a minute.")
    if not response.is_success:
        raise GrokError(f"xAI answered {response.status_code}: {response.text[:200]}")
    try:
        body = response.json()
        return body["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        raise GrokError(f"xAI sent a reply this bot could not read: {response.text[:200]}") from exc


def tool_calls(message: dict) -> list[dict]:
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = {}
        calls.append({"id": call.get("id", ""), "name": function.get("name", ""), "args": args})
    return calls


def text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return (content or "").strip()
