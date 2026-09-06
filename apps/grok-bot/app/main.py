from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Form, Header, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from app import dockerctl, state
from app.brain import answer
from app.settings import settings
from app.telegram import channel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    channel.start()
    try:
        yield
    finally:
        channel.stop()


app = FastAPI(title="Survey Cafe assistant", version="0.1.0", lifespan=lifespan)


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not settings.resto_api_key:
        raise HTTPException(status_code=503, detail="RESTO_API_KEY is not set on the bot")
    if x_api_key != settings.resto_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class ChatIn(BaseModel):
    message: str
    chat: str = "web"


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "grok-bot",
        "model": settings.grok_model if settings.grok_enabled else "",
        "grok": settings.grok_enabled,
        "telegram": channel.status(),
        "docker": dockerctl.socket_ready(),
        "confirm_before_changes": settings.require_confirm,
    }


@app.post("/chat", dependencies=[Depends(require_key)])
def chat(body: ChatIn):
    return {"reply": answer(body.message, chat=body.chat)}


@app.get("/actions", dependencies=[Depends(require_key)])
def actions():
    return {"actions": state.recent_actions(20)}


@app.post("/sms", response_class=Response)
def sms(Body: str = Form(default=""), From: str = Form(default="")):  # noqa: N803 - Twilio sends these names
    """Optional Twilio SMS webhook. Needs a public URL, so Telegram is the easy path."""
    allowed = settings.allowed_chat_ids
    if allowed and From not in allowed:
        reply = "This number is not paired with the Survey Cafe assistant."
    else:
        reply = answer(Body, chat=f"sms:{From}")
    body = f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{escape(reply)}</Message></Response>"
    return Response(content=body, media_type="application/xml")


@app.get("/", response_class=PlainTextResponse)
def index():
    return "Survey Cafe assistant. Text it on Telegram, or POST /chat with X-API-Key."
