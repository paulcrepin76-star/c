"""The assistant page: the same bot you text, in a browser tab."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter()
CHAT_TIMEOUT = httpx.Timeout(180.0, connect=5.0)

EXAMPLES = (
    "How are things today?",
    "How is the server?",
    "Show me the last lines from n8n",
    "What apps can you install?",
    "Install ntfy",
    "Update everything",
)


class AssistantMessage(BaseModel):
    message: str


def bot_url() -> str:
    return (settings.bot_url or "").rstrip("/")


def ask_bot(message: str) -> dict:
    target = bot_url()
    if not target:
        return {"ok": False, "reply": "The assistant container is not configured. Set BOT_URL and start grok-bot."}
    try:
        with httpx.Client(timeout=CHAT_TIMEOUT) as client:
            response = client.post(
                f"{target}/chat",
                headers={"X-API-Key": settings.resto_api_key},
                json={"message": message, "chat": "web"},
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "reply": f"The assistant did not answer: {str(exc)[:160]}"}
    if response.status_code == 401:
        return {"ok": False, "reply": "The assistant rejected the API key. Both containers need the same RESTO_API_KEY."}
    if not response.is_success:
        return {"ok": False, "reply": f"The assistant answered {response.status_code}."}
    return {"ok": True, "reply": (response.json() or {}).get("reply", "")}


def bot_health() -> dict:
    target = bot_url()
    if not target:
        return {"online": False, "reason": "BOT_URL is empty"}
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{target}/health")
    except httpx.HTTPError:
        return {"online": False, "reason": "no answer on the bot port"}
    if not response.is_success:
        return {"online": False, "reason": f"health said {response.status_code}"}
    return {"online": True, **response.json()}


@router.get("/assistant")
def assistant_page(request: Request):
    health = bot_health()
    return request.app.state.templates.TemplateResponse(
        request,
        "assistant.html",
        {"health": health, "examples": EXAMPLES, "page": "assistant"},
    )


@router.post("/assistant/send")
def assistant_send(body: AssistantMessage):
    return ask_bot(body.message)
