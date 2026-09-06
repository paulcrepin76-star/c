"""Plain words the bot understands with no model behind it.

This is the fallback when XAI_API_KEY is empty or xAI is unreachable, so the
phone still works on the night something breaks.
"""

from __future__ import annotations

import re

HELP = """What you can text me:

status — sales, food cost, fridges, what needs you
server — every container, disk, memory
logs n8n — last lines from one container
apps — what I can install
install ntfy — add an app (I ask first)
restart n8n · stop n8n · start n8n
update — git pull and rebuild the whole stack
update n8n — new image for one container
sync — pull Square, Paperless, and Mealie now

Anything I change on the server waits for you to reply yes."""

_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (r"^(help|/help|/start|what can you do|commands)\b", "help", ()),
    (r"^(/status|status|how are things|how is it going|how's it going|how are we|comment ça va|ça va)\b", "restaurant_status", ()),
    (r"^(the )?(restaurant|sales|cellar|cafe|café)\b", "restaurant_status", ()),
    (r"^(/server|server|containers|docker|serveur)\b", "server_status", ()),
    (r"^(/apps|apps|catalog|catalogue|what can you install)\b", "list_catalog", ()),
    (r"^(/sync|sync|synchronise|synchronize)\b", "run_sync", ()),
    (r"^(?:/logs?|logs?)\s+(?P<app>[\w.\-]+)", "app_logs", ("app",)),
    (r"^(?:restart|reboot|redémarre|redemarre)\s+(?P<app>[\w.\-]+)", "restart_app", ("app",)),
    (r"^(?:stop|arrête|arrete)\s+(?P<app>[\w.\-]+)", "stop_app", ("app",)),
    (r"^(?:start|démarre|demarre)\s+(?P<app>[\w.\-]+)", "start_app", ("app",)),
    (r"^(?:remove|delete|uninstall|supprime)\s+(?P<app>[\w.\-]+)", "remove_app", ("app",)),
    (r"^(?:install|installe|add)\s+(?P<app>[\w.\-/:]+)(?:\s+(?:on\s+)?(?:port\s+)?(?P<port>\d{2,5}))?", "install_app", ("app", "port")),
    (r"^(?:/update|update|upgrade|mets? à jour|met a jour)\s+(?P<app>[\w.\-]+)", "update_app", ("app",)),
    (r"^(?:/update|update|upgrade|update everything|mise à jour)\s*$", "update_stack", ()),
)


WHOLE_STACK = {"everything", "all", "stack", "tout", "server"}


def parse(text: str) -> dict | None:
    """Return {'tool': name, 'args': {...}} or None when nothing matches."""
    lowered = " ".join((text or "").strip().split()).lower()
    for pattern, tool, fields in _PATTERNS:
        match = re.match(pattern, lowered)
        if not match:
            continue
        args: dict = {}
        for field in fields:
            value = match.groupdict().get(field)
            if not value:
                continue
            args[field] = int(value) if field == "port" else value
        if tool == "update_app" and args.get("app") in WHOLE_STACK:
            return {"tool": "update_stack", "args": {}}
        if tool == "install_app":
            target = str(args.get("app", ""))
            if "/" in target or ":" in target:
                args = {**args, "app": "", "image": target}
        return {"tool": tool, "args": args}
    return None


def unknown(has_model: bool) -> str:
    if has_model:
        return "I could not reach Grok just now, and that phrasing is not one of my plain commands.\n\n" + HELP
    return "I do not have an xAI key yet, so I only answer plain commands.\n\n" + HELP
