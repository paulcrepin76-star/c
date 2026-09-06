"""Per-chat memory, the pending yes/no, and the audit trail."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from app.settings import settings

_lock = threading.Lock()
_history: dict[str, list[dict]] = {}
_pending: dict[str, dict] = {}


def history(chat: str) -> list[dict]:
    with _lock:
        return list(_history.get(chat, []))


def remember(chat: str, role: str, content: str) -> None:
    with _lock:
        turns = _history.setdefault(chat, [])
        turns.append({"role": role, "content": content})
        limit = max(2, settings.history_turns * 2)
        if len(turns) > limit:
            del turns[: len(turns) - limit]


def forget(chat: str) -> None:
    with _lock:
        _history.pop(chat, None)
        _pending.pop(chat, None)


def set_pending(chat: str, tool: str, args: dict, summary: str) -> None:
    with _lock:
        _pending[chat] = {"tool": tool, "args": args, "summary": summary, "at": time.time()}


def get_pending(chat: str) -> dict | None:
    with _lock:
        found = _pending.get(chat)
        if found is None:
            return None
        if time.time() - found["at"] > settings.confirm_ttl_seconds:
            del _pending[chat]
            return None
        return dict(found)


def clear_pending(chat: str) -> None:
    with _lock:
        _pending.pop(chat, None)


def audit(chat: str, tool: str, args: dict, result: dict) -> None:
    error = result.get("error", "") if isinstance(result, dict) else ""
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "chat": chat,
        "tool": tool,
        "args": args,
        "ok": not error,
        "error": error,
    }
    path = Path(settings.data_dir) / "actions.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def recent_actions(limit: int = 10) -> list[dict]:
    path = Path(settings.data_dir) / "actions.log"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def reset() -> None:
    with _lock:
        _history.clear()
        _pending.clear()
