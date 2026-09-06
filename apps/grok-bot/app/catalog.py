"""Apps the bot is allowed to install, and the compose file it writes them to.

Installed apps land in `compose.extra.yml` next to `compose.yml`, so the stack
stays declarative and a later `docker compose up -d` keeps them running.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.dockerctl import EXTRA_FILE
from app.settings import settings

APPDATA = "${APPDATA:-./appdata}"

CATALOG: tuple[dict, ...] = (
    {
        "slug": "ntfy",
        "name": "ntfy",
        "summary": "Push alerts to your phone. Free, no SMS plan.",
        "image": "binwiederhier/ntfy:latest",
        "port": 8055,
        "target": 80,
        "command": ["serve"],
        "volumes": [f"{APPDATA}/ntfy:/var/lib/ntfy"],
        "environment": {"NTFY_CACHE_FILE": "/var/lib/ntfy/cache.db", "NTFY_AUTH_FILE": "/var/lib/ntfy/auth.db"},
    },
    {
        "slug": "uptime-kuma",
        "name": "Uptime Kuma",
        "summary": "Watches every service and tells you the minute one dies.",
        "image": "louislam/uptime-kuma:1",
        "port": 3011,
        "target": 3001,
        "volumes": [f"{APPDATA}/uptime-kuma:/app/data"],
    },
    {
        "slug": "dozzle",
        "name": "Dozzle",
        "summary": "Live container logs in a browser tab.",
        "image": "amir20/dozzle:latest",
        "port": 8087,
        "target": 8080,
        "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
    },
    {
        "slug": "homepage",
        "name": "Homepage",
        "summary": "One dashboard with a tile per service.",
        "image": "ghcr.io/gethomepage/homepage:latest",
        "port": 3010,
        "target": 3000,
        "volumes": [f"{APPDATA}/homepage:/app/config", "/var/run/docker.sock:/var/run/docker.sock:ro"],
        "environment": {"HOMEPAGE_ALLOWED_HOSTS": "*"},
    },
    {
        "slug": "ollama",
        "name": "Ollama",
        "summary": "Local LLM on the server. Fills OLLAMA_BASE_URL for invoice reading.",
        "image": "ollama/ollama:latest",
        "port": 11434,
        "target": 11434,
        "volumes": [f"{APPDATA}/ollama:/root/.ollama"],
    },
    {
        "slug": "adminer",
        "name": "Adminer",
        "summary": "Small web client for the stack Postgres.",
        "image": "adminer:latest",
        "port": 8091,
        "target": 8080,
        "environment": {"ADMINER_DEFAULT_SERVER": "postgres"},
    },
    {
        "slug": "filebrowser",
        "name": "File Browser",
        "summary": "Browse and upload files on the share from a phone.",
        "image": "filebrowser/filebrowser:s6",
        "port": 8078,
        "target": 80,
        "volumes": [f"{APPDATA}/filebrowser:/config", "${CONSUME_DIR:-./appdata/invoices-inbox}:/srv"],
    },
    {
        "slug": "vaultwarden",
        "name": "Vaultwarden",
        "summary": "Password vault for the supplier logins you type by hand.",
        "image": "vaultwarden/server:latest",
        "port": 8079,
        "target": 80,
        "volumes": [f"{APPDATA}/vaultwarden:/data"],
    },
)

HEADER = (
    "# Apps the assistant installed. Merged on top of compose.yml.\n"
    "# Edit or delete a block, then run: docker compose -f compose.yml -f compose.extra.yml up -d\n"
)


def find_app(slug: str) -> dict | None:
    wanted = (slug or "").strip().lower().replace("_", "-").replace(" ", "-")
    for app in CATALOG:
        if app["slug"] == wanted or app["name"].lower() == wanted:
            return app
    return None


def extra_path() -> Path:
    return Path(settings.repo_dir) / EXTRA_FILE


def load_extra() -> dict:
    path = extra_path()
    if not path.exists():
        return {"services": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"services": {}}
    if not isinstance(data, dict):
        return {"services": {}}
    data.setdefault("services", {})
    return data


def save_extra(data: dict) -> None:
    path = extra_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    path.write_text(HEADER + body, encoding="utf-8")


def installed() -> list[str]:
    return sorted((load_extra().get("services") or {}).keys())


def service_definition(app: dict) -> dict:
    service: dict = {
        "image": app["image"],
        "container_name": f"{settings.compose_project}-{app['slug']}",
        "restart": "unless-stopped",
    }
    if app.get("command"):
        service["command"] = list(app["command"])
    if app.get("port"):
        service["ports"] = [f"{app['port']}:{app.get('target', app['port'])}"]
    if app.get("volumes"):
        service["volumes"] = list(app["volumes"])
    environment = {"TZ": "${TZ:-America/New_York}", **(app.get("environment") or {})}
    service["environment"] = environment
    service["networks"] = ["resto"]
    return service


def custom_app(slug: str, image: str, port: int | None = None, target: int | None = None) -> dict:
    clean = (slug or image.split("/")[-1].split(":")[0]).strip().lower().replace("_", "-").replace(" ", "-")
    return {
        "slug": clean,
        "name": clean,
        "summary": f"Custom container from {image}.",
        "image": image,
        "port": port,
        "target": target or port,
        "volumes": [f"{APPDATA}/{clean}:/config"] if port else [],
    }


def add_service(app: dict) -> str:
    data = load_extra()
    data["services"][app["slug"]] = service_definition(app)
    save_extra(data)
    return app["slug"]


def remove_service(slug: str) -> bool:
    data = load_extra()
    if slug not in data.get("services", {}):
        return False
    del data["services"][slug]
    save_extra(data)
    return True


def port_conflict(app: dict) -> str:
    """Cheap guard so an install does not fight compose.yml for a port."""
    port = app.get("port")
    if not port:
        return ""
    root = Path(settings.repo_dir) / "compose.yml"
    if not root.exists():
        return ""
    needle = f'"{port}:'
    for line in root.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and needle in stripped:
            return f"Port {port} is already published by compose.yml."
    return ""


def catalog_rows() -> list[dict]:
    live = set(installed())
    return [
        {
            "slug": app["slug"],
            "name": app["name"],
            "summary": app["summary"],
            "image": app["image"],
            "port": app.get("port"),
            "installed": app["slug"] in live,
        }
        for app in CATALOG
    ]
