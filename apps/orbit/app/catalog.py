"""Known apps: colors, icons, groups, and default links."""

from __future__ import annotations

from app.settings import settings

# icon keys map to SVG symbols in the page.
CATALOG: list[dict] = [
    {
        "id": "resto-core",
        "name": "Cellar",
        "group": "Kitchen",
        "icon": "wine",
        "color": "#d4ff4a",
        "match": ("resto-core", "resto_core"),
        "href_attr": "cellar_url",
        "description": "Wine, costing, inventory",
    },
    {
        "id": "paperless",
        "name": "Paperless",
        "group": "Kitchen",
        "icon": "docs",
        "color": "#7cf4e0",
        "match": ("paperless",),
        "href_attr": "paperless_url",
        "description": "Invoice archive",
    },
    {
        "id": "mealie",
        "name": "Mealie",
        "group": "Kitchen",
        "icon": "fork",
        "color": "#ffb020",
        "match": ("mealie",),
        "href_attr": "mealie_url",
        "description": "Recipes",
    },
    {
        "id": "n8n",
        "name": "n8n",
        "group": "Kitchen",
        "icon": "flow",
        "color": "#ff6b8a",
        "match": ("n8n",),
        "href_attr": "n8n_url",
        "description": "Nightly sync",
    },
    {
        "id": "metabase",
        "name": "Metabase",
        "group": "Kitchen",
        "icon": "chart",
        "color": "#5b8dff",
        "match": ("metabase",),
        "href_attr": "metabase_url",
        "description": "Charts",
    },
    {
        "id": "postgres",
        "name": "Postgres",
        "group": "System",
        "icon": "db",
        "color": "#6ea8fe",
        "match": ("postgres", "postgresql"),
        "href": "",
        "description": "Shared database",
    },
    {
        "id": "redis",
        "name": "Redis",
        "group": "System",
        "icon": "bolt",
        "color": "#ff5d5d",
        "match": ("redis",),
        "href": "",
        "description": "Cache",
    },
    {
        "id": "homeassistant",
        "name": "Home Assistant",
        "group": "House",
        "icon": "home",
        "color": "#41bdf5",
        "match": ("homeassistant", "home-assistant"),
        "href_attr": "homeassistant_url",
        "description": "Fridge sensors",
    },
    {
        "id": "frigate",
        "name": "Frigate",
        "group": "House",
        "icon": "cam",
        "color": "#7c5cff",
        "match": ("frigate",),
        "href_attr": "frigate_url",
        "description": "Cameras",
    },
    {
        "id": "mosquitto",
        "name": "Mosquitto",
        "group": "System",
        "icon": "radio",
        "color": "#3ddc97",
        "match": ("mosquitto", "mqtt"),
        "href": "",
        "description": "MQTT",
    },
    {
        "id": "price-collector",
        "name": "Collector",
        "group": "Kitchen",
        "icon": "scan",
        "color": "#ffc857",
        "match": ("price-collector", "price_collector"),
        "href": "http://100.116.48.120:7900",
        "description": "Supplier login",
    },
    {
        "id": "sonarr",
        "name": "Series",
        "group": "Library",
        "icon": "series",
        "color": "#00a5e4",
        "match": ("sonarr",),
        "href_attr": "sonarr_url",
        "description": "TV library",
    },
    {
        "id": "radarr",
        "name": "Films",
        "group": "Library",
        "icon": "film",
        "color": "#ffc230",
        "match": ("radarr",),
        "href_attr": "radarr_url",
        "description": "Film library",
    },
    {
        "id": "prowlarr",
        "name": "Indexers",
        "group": "Library",
        "icon": "radar",
        "color": "#e66060",
        "match": ("prowlarr",),
        "href_attr": "prowlarr_url",
        "description": "Indexers",
    },
    {
        "id": "qbittorrent",
        "name": "Grabs",
        "group": "Library",
        "icon": "grab",
        "color": "#2f67ba",
        "match": ("qbittorrent", "qbittorrent", "transmission", "sabnzbd"),
        "href_attr": "qbit_url",
        "description": "Downloads",
    },
    {
        "id": "jellyfin",
        "name": "Screen",
        "group": "Library",
        "icon": "screen",
        "color": "#aa5cc3",
        "match": ("jellyfin", "plex", "emby"),
        "href_attr": "jellyfin_url",
        "description": "Watch",
    },
    {
        "id": "gotenberg",
        "name": "Gotenberg",
        "group": "System",
        "icon": "print",
        "color": "#9aa4b2",
        "match": ("gotenberg",),
        "href": "",
        "description": "PDF engine",
    },
    {
        "id": "tika",
        "name": "Tika",
        "group": "System",
        "icon": "scan",
        "color": "#8b93a7",
        "match": ("tika",),
        "href": "",
        "description": "OCR helper",
    },
    {
        "id": "orbit",
        "name": "Orbit",
        "group": "System",
        "icon": "orbit",
        "color": "#d4ff4a",
        "match": ("orbit", "resto-orbit"),
        "href_attr": "public_url",
        "description": "This page",
    },
]


GROUP_ORDER = ("Kitchen", "House", "Library", "System", "Other")


def _href_for(entry: dict) -> str:
    attr = entry.get("href_attr")
    if attr:
        return str(getattr(settings, attr, "") or "")
    return str(entry.get("href") or "")


def match_service(name: str, image: str = "", labels: dict | None = None) -> dict:
    labels = labels or {}
    hay = f"{name} {image}".lower()
    found = None
    for entry in CATALOG:
        if any(token in hay for token in entry["match"]):
            found = entry
            break
    icon = "box"
    color = "#8b93a7"
    group = "Other"
    title = name.replace("resto-", "").replace("_", " ").title()
    href = ""
    description = ""
    if found:
        icon = found["icon"]
        color = found["color"]
        group = found["group"]
        title = found["name"]
        href = _href_for(found)
        description = found.get("description") or ""
    if labels.get("homepage.name"):
        title = labels["homepage.name"]
    if labels.get("orbit.name"):
        title = labels["orbit.name"]
    if labels.get("homepage.icon"):
        icon = _icon_from_label(labels["homepage.icon"], icon)
    if labels.get("orbit.icon"):
        icon = _icon_from_label(labels["orbit.icon"], icon)
    if labels.get("homepage.href"):
        href = labels["homepage.href"]
    if labels.get("orbit.href"):
        href = labels["orbit.href"]
    if labels.get("homepage.group"):
        group = labels["homepage.group"]
    if labels.get("orbit.group"):
        group = labels["orbit.group"]
    if labels.get("homepage.description"):
        description = labels["homepage.description"]
    return {
        "title": title,
        "icon": icon,
        "color": color,
        "group": group,
        "href": href,
        "description": description,
    }


def _icon_from_label(raw: str, fallback: str) -> str:
    key = raw.lower().replace(".png", "").replace(".svg", "").replace("mdi-", "")
    aliases = {
        "home-assistant": "home",
        "homeassistant": "home",
        "frigate": "cam",
        "sonarr": "series",
        "radarr": "film",
        "qbittorrent": "grab",
        "jellyfin": "screen",
        "paperless-ngx": "docs",
        "postgres": "db",
        "postgresql": "db",
    }
    known = {entry["icon"] for entry in CATALOG} | {"box", "folder"}
    mapped = aliases.get(key, key)
    return mapped if mapped in known else fallback


def library_apps() -> list[dict]:
    wanted = ("radarr", "sonarr", "qbittorrent", "jellyfin", "prowlarr")
    rows = []
    for entry in CATALOG:
        if entry["id"] in wanted:
            href = _href_for(entry)
            rows.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "icon": entry["icon"],
                    "color": entry["color"],
                    "href": href,
                    "linked": bool(href),
                    "description": entry["description"],
                    "group": "Library",
                }
            )
    return rows


def kitchen_and_house() -> list[dict]:
    rows = []
    for entry in CATALOG:
        if entry["group"] in ("Kitchen", "House") and entry.get("href_attr"):
            href = _href_for(entry)
            if href:
                rows.append(
                    {
                        "id": entry["id"],
                        "name": entry["name"],
                        "icon": entry["icon"],
                        "color": entry["color"],
                        "href": href,
                        "description": entry["description"],
                        "group": entry["group"],
                    }
                )
    return rows
