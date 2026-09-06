"""The things the bot can actually do, and the schema Grok sees."""

from __future__ import annotations

from app import catalog, dockerctl, resto
from app.dockerctl import DockerError
from app.settings import settings


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


# Everything in here changes the server, so it waits for a yes.
CONFIRM_TOOLS = {"restart_app", "stop_app", "start_app", "install_app", "remove_app", "update_app", "update_stack"}


def restaurant_status() -> dict:
    return resto.restaurant_status()


def server_status() -> dict:
    try:
        rows = dockerctl.containers()
        engine = dockerctl.engine_info()
    except DockerError as exc:
        return {"error": str(exc)}
    down = [row["name"] for row in rows if row["state"] != "running"]
    unhealthy = [row["name"] for row in rows if row["health"] == "unhealthy"]
    return {
        "engine": engine,
        "host": dockerctl.host_health(),
        "containers": [
            {"name": row["name"], "state": row["state"], "status": row["status"], "health": row["health"], "ports": row["ports"]}
            for row in rows
        ],
        "not_running": down,
        "unhealthy": unhealthy,
    }


def app_logs(app: str, lines: int = 40) -> dict:
    try:
        found = dockerctl.find_container(app)
        if found is None:
            return {"error": f"No container matches '{app}'."}
        return {"app": found["name"], "state": found["state"], "logs": dockerctl.tail(dockerctl.logs(found["name"], lines), 1500)}
    except DockerError as exc:
        return {"error": str(exc)}


def list_catalog() -> dict:
    return {
        "installable": catalog.catalog_rows(),
        "installed_by_bot": catalog.installed(),
        "custom_images_allowed": settings.allow_custom_images,
    }


def _lifecycle(app: str, action: str) -> dict:
    try:
        found = dockerctl.find_container(app)
        if found is None:
            return {"error": f"No container matches '{app}'."}
        dockerctl.lifecycle(found["name"], action)
        after = dockerctl.find_container(found["name"]) or found
        return {"ok": True, "app": found["name"], "action": action, "state": after["state"], "status": after["status"]}
    except DockerError as exc:
        return {"error": str(exc)}


def restart_app(app: str) -> dict:
    return _lifecycle(app, "restart")


def stop_app(app: str) -> dict:
    return _lifecycle(app, "stop")


def start_app(app: str) -> dict:
    return _lifecycle(app, "start")


def install_app(app: str = "", image: str = "", port: int | None = None) -> dict:
    known = catalog.find_app(app) if app else None
    if known is None:
        if not image:
            names = ", ".join(row["slug"] for row in catalog.catalog_rows())
            return {"error": f"'{app}' is not in the catalog. Known apps: {names}. Pass an image to install something else."}
        if not settings.allow_custom_images:
            return {"error": "Custom images are turned off. Set BOT_ALLOW_CUSTOM_IMAGES=true to allow them."}
        known = catalog.custom_app(app, image, port)
    elif port:
        known = {**known, "port": port}
    clash = catalog.port_conflict(known)
    if clash:
        return {"error": clash}
    slug = catalog.add_service(known)
    result = dockerctl.compose("up", "-d", slug)
    if not result["ok"]:
        catalog.remove_service(slug)
        return {"error": f"Install failed, rolled the compose file back.\n{dockerctl.tail(result['output'], 800)}"}
    return {
        "ok": True,
        "app": slug,
        "image": known["image"],
        "port": known.get("port"),
        "output": dockerctl.tail(result["output"], 600),
    }


def remove_app(app: str) -> dict:
    slug = (app or "").strip().lower()
    if slug not in catalog.installed():
        return {"error": f"'{app}' was not installed by the assistant, so it will not remove it."}
    result = dockerctl.compose("rm", "-sf", slug)
    catalog.remove_service(slug)
    return {"ok": result["ok"], "app": slug, "output": dockerctl.tail(result["output"], 600)}


def update_app(app: str) -> dict:
    found = None
    try:
        found = dockerctl.find_container(app)
    except DockerError as exc:
        return {"error": str(exc)}
    service = (found or {}).get("service") or (app or "").strip().lower()
    pulled = dockerctl.compose("pull", service)
    if not pulled["ok"]:
        return {"error": f"Could not pull a new image for '{service}'.\n{dockerctl.tail(pulled['output'], 800)}"}
    upped = dockerctl.compose("up", "-d", service)
    return {
        "ok": upped["ok"],
        "app": service,
        "output": dockerctl.tail(f"{pulled['output']}\n{upped['output']}", 800),
    }


def update_stack() -> dict:
    pulled = dockerctl.git_pull()
    upped = dockerctl.compose("up", "-d", "--build")
    return {
        "ok": upped["ok"],
        "git": dockerctl.tail(pulled["output"], 400),
        "compose": dockerctl.tail(upped["output"], 900),
    }


def run_sync() -> dict:
    return resto.run_sync()


HANDLERS = {
    "restaurant_status": restaurant_status,
    "server_status": server_status,
    "app_logs": app_logs,
    "list_catalog": list_catalog,
    "restart_app": restart_app,
    "stop_app": stop_app,
    "start_app": start_app,
    "install_app": install_app,
    "remove_app": remove_app,
    "update_app": update_app,
    "update_stack": update_stack,
    "run_sync": run_sync,
}

SCHEMAS = [
    _tool(
        "restaurant_status",
        "Sales, food and wine cost, fridge temperatures, and anything that needs the owner today. Use this for 'how are things' about the restaurant.",
        {},
    ),
    _tool(
        "server_status",
        "Every container on the Unraid server with its state and health, plus load, memory, and free disk. Use this for 'how is the server'.",
        {},
    ),
    _tool(
        "app_logs",
        "Recent log lines for one container, to explain why it is down or unhealthy.",
        {
            "app": {"type": "string", "description": "Container or compose service name, e.g. n8n or resto-core."},
            "lines": {"type": "integer", "description": "How many lines, 1-200. Default 40."},
        },
        ["app"],
    ),
    _tool("list_catalog", "Apps the assistant can install, and which ones it already installed.", {}),
    _tool("restart_app", "Restart one container.", {"app": {"type": "string"}}, ["app"]),
    _tool("stop_app", "Stop one container.", {"app": {"type": "string"}}, ["app"]),
    _tool("start_app", "Start a stopped container.", {"app": {"type": "string"}}, ["app"]),
    _tool(
        "install_app",
        "Install a new app or container on the server. Prefer a catalog slug from list_catalog; pass image for anything else.",
        {
            "app": {"type": "string", "description": "Catalog slug, or the name to give a custom container."},
            "image": {"type": "string", "description": "Docker image, only for apps outside the catalog."},
            "port": {"type": "integer", "description": "Host port to publish."},
        },
    ),
    _tool("remove_app", "Remove an app the assistant installed earlier.", {"app": {"type": "string"}}, ["app"]),
    _tool("update_app", "Pull a newer image for one container and recreate it.", {"app": {"type": "string"}}, ["app"]),
    _tool("update_stack", "Update everything: git pull the repo, rebuild, and restart the whole stack.", {}),
    _tool("run_sync", "Pull Square sales, Paperless invoices, and Mealie recipes into the cellar app now.", {}),
]


def needs_confirm(name: str) -> bool:
    return settings.require_confirm and name in CONFIRM_TOOLS


def describe(name: str, args: dict) -> str:
    app = str(args.get("app") or "").strip()
    image = str(args.get("image") or "").strip()
    sentences = {
        "restart_app": f"restart {app}",
        "stop_app": f"stop {app}",
        "start_app": f"start {app}",
        "remove_app": f"remove {app} from the server",
        "update_app": f"pull a new image for {app} and recreate it",
        "update_stack": "git pull the repo, rebuild, and restart the whole stack",
        "install_app": f"install {app or image}" + (f" from {image}" if app and image else ""),
    }
    return sentences.get(name, f"run {name}")


def run(name: str, args: dict | None = None) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return handler(**(args or {}))
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{name} failed: {str(exc)[:300]}"}
