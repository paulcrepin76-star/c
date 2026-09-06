"""Telegram long polling.

The bot calls out to api.telegram.org, so Unraid needs no open port, no
public URL, and no reverse proxy. Nothing can reach the server this way
except the chat ids you listed.
"""

from __future__ import annotations

import logging
import threading

import httpx

from app.brain import answer
from app.settings import settings

log = logging.getLogger("grok-bot.telegram")
MAX_MESSAGE = 3800


class TelegramChannel:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0
        self.last_error = ""
        self.messages = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.telegram_bot_token)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _url(self, method: str) -> str:
        return f"{settings.telegram_api_base.rstrip('/')}/bot{settings.telegram_bot_token}/{method}"

    def call(self, method: str, payload: dict, timeout: float = 20.0) -> dict:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(self._url(method), json=payload)
        if not response.is_success:
            raise httpx.HTTPError(f"{method} answered {response.status_code}: {response.text[:200]}")
        return response.json()

    def send(self, chat_id: str | int, text: str) -> None:
        body = text or "…"
        while body:
            chunk, body = body[:MAX_MESSAGE], body[MAX_MESSAGE:]
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})

    def whoami(self) -> dict:
        try:
            return self.call("getMe", {}).get("result") or {}
        except httpx.HTTPError as exc:
            self.last_error = str(exc)[:200]
            return {}

    def _allowed(self, chat_id: str) -> bool:
        return chat_id in settings.allowed_chat_ids

    def reply_to(self, chat_id: str, text: str) -> str:
        if not settings.allowed_chat_ids:
            return (
                "This bot is not paired yet.\n\n"
                f"Your chat id is {chat_id}.\n"
                f"Put TELEGRAM_ALLOWED_CHAT_IDS={chat_id} in .env on the server, then "
                "docker compose up -d grok-bot."
            )
        if not self._allowed(chat_id):
            return "This bot only answers the Survey Cafe owner."
        return answer(text, chat=f"tg:{chat_id}")

    def handle(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = str(((message.get("chat") or {}).get("id")) or "")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        self.messages += 1
        try:
            self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10.0)
        except httpx.HTTPError:
            pass
        try:
            reply = self.reply_to(chat_id, text)
        except Exception as exc:  # noqa: BLE001
            log.exception("bot failed on a message")
            reply = f"That broke on my side: {str(exc)[:200]}"
        try:
            self.send(chat_id, reply)
        except httpx.HTTPError as exc:
            self.last_error = str(exc)[:200]
            log.warning("could not send the reply: %s", self.last_error)

    def poll_once(self) -> int:
        payload = {"offset": self._offset, "timeout": settings.telegram_poll_seconds, "allowed_updates": ["message"]}
        body = self.call("getUpdates", payload, timeout=settings.telegram_poll_seconds + 15)
        updates = body.get("result") or []
        for update in updates:
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            self.handle(update)
        return len(updates)

    def _loop(self) -> None:
        backoff = 5
        me = self.whoami()
        if me:
            log.info("telegram connected as @%s", me.get("username", "?"))
        while not self._stop.is_set():
            try:
                self.poll_once()
                self.last_error = ""
                backoff = 5
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)[:200]
                log.warning("telegram poll failed: %s", self.last_error)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 120)

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="telegram-poll")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "paired_chats": len(settings.allowed_chat_ids),
            "messages": self.messages,
            "last_error": self.last_error,
        }


channel = TelegramChannel()
