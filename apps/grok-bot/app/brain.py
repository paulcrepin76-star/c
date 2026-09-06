"""One text message in, one answer out."""

from __future__ import annotations

import json

from app import commands, grok, render, state, tools
from app.grok import GrokError
from app.settings import settings

SYSTEM_PROMPT = """You are the Survey Cafe assistant. You run on the owner's Unraid server in Bonita Springs, Florida, and you answer him by text message on his phone.

The server runs one Docker Compose stack: resto-core (the cellar, costing, and sales board on port 8088), postgres, n8n, metabase, price-collector, home assistant, frigate, mosquitto. Paperless and Mealie run beside it.

How to answer:
- Use the tools. Never guess a number, a container state, or a price.
- Keep it short enough to read on a phone. Plain sentences, no markdown tables, no headings.
- Lead with the answer. Add detail only if it changes what he should do.
- Answer in the language he wrote in. He writes English and French.
- If a tool returns an error, say plainly what failed and the one thing to check.
- When he asks to change the server, call the tool. The system asks him to confirm before anything runs, so you never need to ask permission yourself.
- Money in dollars, temperatures in Fahrenheit."""

AFFIRMATIVE = {"yes", "y", "yep", "yeah", "yup", "ok", "okay", "go", "do it", "confirm", "sure", "please", "oui", "vas-y", "vasy", "d'accord"}
NEGATIVE = {"no", "n", "nope", "cancel", "stop", "nevermind", "never mind", "non", "annule", "annuler"}


def _confirm_prompt(summary: str) -> str:
    return f"I am about to {summary}.\n\nReply yes to run it, no to drop it."


def _execute(chat: str, tool: str, args: dict) -> str:
    result = tools.run(tool, args)
    state.audit(chat, tool, args, result)
    reply = render.render(tool, result)
    state.remember(chat, "assistant", reply)
    return reply


def _run_or_ask(chat: str, tool: str, args: dict) -> str:
    if tools.needs_confirm(tool):
        summary = tools.describe(tool, args)
        state.set_pending(chat, tool, args, summary)
        return _confirm_prompt(summary)
    return _execute(chat, tool, args)


def _grok_answer(chat: str, text: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += state.history(chat)
    messages.append({"role": "user", "content": text})
    for _ in range(settings.grok_max_rounds):
        message = grok.complete(messages, tools=tools.SCHEMAS, conversation=chat)
        calls = grok.tool_calls(message)
        if not calls:
            reply = grok.text_of(message) or "I do not have an answer for that."
            state.remember(chat, "user", text)
            state.remember(chat, "assistant", reply)
            return reply
        gated = next((call for call in calls if tools.needs_confirm(call["name"])), None)
        if gated is not None:
            summary = tools.describe(gated["name"], gated["args"])
            state.set_pending(chat, gated["name"], gated["args"], summary)
            state.remember(chat, "user", text)
            return _confirm_prompt(summary)
        messages.append(
            {"role": "assistant", "content": message.get("content") or "", "tool_calls": message.get("tool_calls")}
        )
        for call in calls:
            result = tools.run(call["name"], call["args"])
            state.audit(chat, call["name"], call["args"], result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, default=str)[:12000],
                }
            )
    return "I kept looking things up and never landed on an answer. Ask me for one thing at a time."


def answer(text: str, chat: str = "web") -> str:
    clean = (text or "").strip()
    if not clean:
        return commands.HELP
    lowered = clean.lower().rstrip("!. ")

    pending = state.get_pending(chat)
    if pending is not None:
        if lowered in AFFIRMATIVE:
            state.clear_pending(chat)
            return _execute(chat, pending["tool"], pending["args"])
        if lowered in NEGATIVE:
            state.clear_pending(chat)
            return "Dropped it. Nothing changed on the server."
        state.clear_pending(chat)

    if lowered in ("/help", "help", "/start"):
        return commands.HELP
    if lowered in ("/cancel", "cancel"):
        return "Nothing was waiting."
    if lowered in ("/forget", "forget", "/reset"):
        state.forget(chat)
        return "Forgot the conversation. Start fresh."

    direct = commands.parse(clean)
    if settings.grok_enabled:
        try:
            return _grok_answer(chat, clean)
        except GrokError as exc:
            if direct is None:
                return f"{exc}\n\n{commands.unknown(True)}"
            return f"({exc})\n\n" + _run_or_ask(chat, direct["tool"], direct["args"])
    if direct is None:
        return commands.unknown(False)
    return _run_or_ask(chat, direct["tool"], direct["args"])
