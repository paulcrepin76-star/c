"""Docker containers with catalog icons."""

from __future__ import annotations

from collections import defaultdict

from app.catalog import GROUP_ORDER, match_service

DEMO_CONTAINERS = [
    {"name": "resto-core", "image": "resto-core:local", "state": "running", "status": "Up 2 days", "ports": ["8088:8080"], "labels": {}},
    {"name": "resto-paperless", "image": "ghcr.io/paperless-ngx/paperless-ngx:latest", "state": "running", "status": "Up 2 days", "ports": ["8010:8000"], "labels": {}},
    {"name": "resto-mealie", "image": "ghcr.io/mealie-recipes/mealie:latest", "state": "running", "status": "Up 2 days", "ports": ["9925:9000"], "labels": {}},
    {"name": "resto-n8n", "image": "docker.n8n.io/n8nio/n8n:latest", "state": "running", "status": "Up 2 days", "ports": ["5678:5678"], "labels": {}},
    {"name": "resto-metabase", "image": "metabase/metabase:latest", "state": "running", "status": "Up 2 days", "ports": ["3001:3000"], "labels": {}},
    {"name": "resto-postgres", "image": "postgres:16-alpine", "state": "running", "status": "Up 2 days", "ports": ["5433:5432"], "labels": {}},
    {"name": "resto-homeassistant", "image": "ghcr.io/home-assistant/home-assistant:stable", "state": "running", "status": "Up 12 hours", "ports": ["8123:8123"], "labels": {"homepage.group": "House", "homepage.name": "Home Assistant"}},
    {"name": "resto-frigate", "image": "ghcr.io/blakeblackshear/frigate:stable", "state": "running", "status": "Up 12 hours", "ports": ["8971:8971"], "labels": {"homepage.group": "House"}},
    {"name": "resto-mosquitto", "image": "eclipse-mosquitto:2", "state": "running", "status": "Up 12 hours", "ports": [], "labels": {}},
    {"name": "resto-price-collector", "image": "resto-price-collector:local", "state": "running", "status": "Up 2 days", "ports": ["8099:8099", "7900:7900"], "labels": {}},
    {"name": "sonarr", "image": "lscr.io/linuxserver/sonarr:latest", "state": "running", "status": "Up 5 hours", "ports": ["8989:8989"], "labels": {}},
    {"name": "radarr", "image": "lscr.io/linuxserver/radarr:latest", "state": "running", "status": "Up 5 hours", "ports": ["7878:7878"], "labels": {}},
    {"name": "qbittorrent", "image": "lscr.io/linuxserver/qbittorrent:latest", "state": "running", "status": "Up 5 hours", "ports": ["8080:8080"], "labels": {}},
    {"name": "jellyfin", "image": "lscr.io/linuxserver/jellyfin:latest", "state": "exited", "status": "Exited (0) 3 hours ago", "ports": ["8096:8096"], "labels": {}},
]


def _ports_of(container) -> list[str]:
    ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
    shown: list[str] = []
    for private, binds in ports.items():
        if not binds:
            continue
        for bind in binds:
            host = bind.get("HostPort")
            if host:
                shown.append(f"{host}:{private.split('/')[0]}")
    return shown[:4]


def _live_containers() -> list[dict] | None:
    try:
        import docker
    except ImportError:
        return None
    try:
        client = docker.from_env()
        client.ping()
    except Exception:
        return None
    rows = []
    try:
        for container in client.containers.list(all=True):
            labels = container.labels or {}
            image = ""
            try:
                image = container.image.tags[0] if container.image.tags else container.image.short_id
            except Exception:
                image = str(container.attrs.get("Config", {}).get("Image") or "")
            rows.append(
                {
                    "id": container.short_id,
                    "name": container.name,
                    "image": image,
                    "state": container.status,
                    "status": container.attrs.get("State", {}).get("Status") or container.status,
                    "ports": _ports_of(container),
                    "labels": labels,
                }
            )
    except Exception:
        return None
    return rows


def _decorate(raw: dict) -> dict:
    meta = match_service(raw.get("name", ""), raw.get("image", ""), raw.get("labels") or {})
    state = (raw.get("state") or "").lower()
    running = state in {"running", "restarting"}
    return {
        "id": raw.get("id") or raw.get("name"),
        "name": raw.get("name"),
        "image": raw.get("image"),
        "state": state or "unknown",
        "running": running,
        "status": raw.get("status") or state,
        "ports": raw.get("ports") or [],
        **meta,
    }


def snapshot() -> dict:
    live = _live_containers()
    demo = live is None
    source = live if live is not None else DEMO_CONTAINERS
    items = [_decorate(row) for row in source]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["group"]].append(item)
    groups = []
    for name in GROUP_ORDER:
        if name in grouped:
            groups.append({"name": name, "items": grouped.pop(name)})
    for name in sorted(grouped):
        groups.append({"name": name, "items": grouped[name]})
    running = sum(1 for item in items if item["running"])
    return {
        "demo": demo,
        "total": len(items),
        "running": running,
        "stopped": len(items) - running,
        "groups": groups,
        "items": items,
    }
