"""Turn tool results into something worth reading on a phone."""

from __future__ import annotations

from urllib.parse import urlparse

from app.settings import settings


def money(value) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(amount) >= 1000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def pct(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def public_host() -> str:
    source = settings.public_url or settings.resto_url
    host = urlparse(source).hostname or ""
    return host


def _dot(state: str, health: str) -> str:
    if state != "running":
        return "down"
    if health == "unhealthy":
        return "unhealthy"
    if health == "starting":
        return "starting"
    return "up"


def restaurant(result: dict) -> str:
    if result.get("error"):
        return f"Could not read the restaurant board. {result['error']}"
    sales = result.get("sales") or {}
    month = result.get("month") or {}
    fridges = result.get("fridges") or {}
    lines = [
        f"Today {money(sales.get('today'))} on {int(sales.get('tickets_today') or 0)} tickets.",
        f"Month to date {money(sales.get('month_to_date'))}, food {pct(month.get('food_cost_pct'))}, wine {pct(month.get('wine_cost_pct'))}.",
        f"Operating profit this month {money(month.get('operating_profit'))}.",
    ]
    alerts = fridges.get("alerts") or 0
    online = fridges.get("online") or 0
    total = fridges.get("total") or 0
    if alerts:
        names = ", ".join(f"{row['name']} {row.get('temp_f')}F" for row in (fridges.get("out_of_range") or [])[:4])
        lines.append(f"Fridges: {alerts} out of range — {names}.")
    elif not online:
        lines.append(f"Fridges: none of the {total} are reporting a temperature.")
    elif online < total:
        lines.append(f"Fridges: {online} of {total} reporting, all in range.")
    else:
        lines.append(f"Fridges: all {total} in range.")
    below = result.get("wine_below_par") or []
    if below:
        lines.append(f"Wine under par: {', '.join(below[:5])}.")
    needs = result.get("needs_you") or []
    if needs:
        lines.append("Needs you:")
        lines += [f"· {item}" for item in needs[:5]]
    return "\n".join(lines)


def server(result: dict) -> str:
    if result.get("error"):
        return f"Could not reach Docker. {result['error']}"
    host = result.get("host") or {}
    disk = host.get("disk") or {}
    engine = result.get("engine") or {}
    rows = result.get("containers") or []
    lines = [
        f"{engine.get('running', 0)} of {len(rows)} containers running.",
        f"Disk {disk.get('used_pct', 0)}% used, {disk.get('free_gb', 0)} GB free.",
    ]
    memory = host.get("memory_used_pct")
    load = host.get("load") or []
    if memory is not None:
        lines.append(f"Memory {memory}% used, load {load[0] if load else '—'}.")
    for row in rows:
        mark = _dot(row.get("state", ""), row.get("health", ""))
        ports = f" :{row['ports'][0].split('->')[0]}" if row.get("ports") else ""
        lines.append(f"· {row['name']}{ports} — {mark}")
    return "\n".join(lines)


def logs(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    return f"{result['app']} ({result['state']}):\n{result.get('logs') or 'No log lines.'}"


def catalog(result: dict) -> str:
    lines = ["Apps I can install:"]
    for row in result.get("installable") or []:
        mark = " — installed" if row.get("installed") else ""
        lines.append(f"· {row['slug']} — {row['summary']}{mark}")
    if result.get("custom_images_allowed"):
        lines.append("Or name any Docker image and a port.")
    return "\n".join(lines)


VERBS = {"restart": "Restarted", "stop": "Stopped", "start": "Started"}


def lifecycle(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    verb = VERBS.get(result.get("action", ""), "Changed")
    state = result.get("state", "")
    if state == "running":
        return f"{verb} {result['app']}. It is running."
    return f"{verb} {result['app']}. It is now {state or 'in an unknown state'}."


def installed(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    host = public_host()
    port = result.get("port")
    where = f" Open http://{host}:{port}" if host and port else ""
    return f"Installed {result['app']} from {result['image']}.{where}"


def removed(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    return f"Removed {result['app']} and took it out of compose.extra.yml."


def updated(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    head = f"Updated {result['app']}." if result.get("ok") else f"Update of {result.get('app')} did not finish."
    return f"{head}\n{result.get('output', '')}".strip()


def stack(result: dict) -> str:
    head = "Stack updated." if result.get("ok") else "Stack update hit a problem."
    return f"{head}\n{result.get('git', '')}\n{result.get('compose', '')}".strip()


def sync(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    parts = [f"{key}: {value}" for key, value in result.items() if not isinstance(value, (dict, list))]
    return "Sync finished. " + (", ".join(parts) if parts else "Nothing new.")


RENDERERS = {
    "restaurant_status": restaurant,
    "server_status": server,
    "app_logs": logs,
    "list_catalog": catalog,
    "restart_app": lifecycle,
    "stop_app": lifecycle,
    "start_app": lifecycle,
    "install_app": installed,
    "remove_app": removed,
    "update_app": updated,
    "update_stack": stack,
    "run_sync": sync,
}


def render(name: str, result: dict) -> str:
    renderer = RENDERERS.get(name)
    if renderer is None:
        return str(result)
    return renderer(result or {})
