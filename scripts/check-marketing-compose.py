#!/usr/bin/env python3
"""Fail if the marketing stack can start existing services or float image tags."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.marketing.yml"
PUBLIC = ROOT / "compose.public-edge.yml"
DOCKERFILE = ROOT / "apps" / "command" / "Dockerfile"
UP = ROOT / "scripts" / "up-marketing.sh"
SETUP = ROOT / "scripts" / "setup.sh"
NAMES = ROOT / "scripts" / "marketing-names.sh"

PROTECTED = {
    "postgres",
    "n8n",
    "redis",
    "paperless",
    "mealie",
    "resto-core",
    "metabase",
    "homeassistant",
    "frigate",
    "price-collector",
    "mosquitto",
    "gotenberg",
    "tika",
}

PATCH_TAG = re.compile(r"(?:^v)?\d+\.\d+\.\d+")
POSTGRES_TAG = re.compile(r"\d+\.\d+(?:-[A-Za-z0-9.]+)?$")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def images(text: str) -> list[str]:
    found = re.findall(r"(?m)^(?:FROM |[ \t]*image:[ \t]*)(\S+)", text)
    return [item.strip("\"'") for item in found]


def unpinned(image: str) -> str | None:
    if image.startswith("resto-command:"):
        return None
    if ":" not in image or image.endswith(":latest") or ":latest@" in image:
        return f"{image} is not a pinned production tag"
    name, tag = image.rsplit(":", 1)
    tag = tag.split("@", 1)[0]
    if tag in {"latest", "stable", "lts"}:
        return f"{image} is not a pinned production tag"
    if name == "postgres" or name.endswith("/postgres"):
        if POSTGRES_TAG.fullmatch(tag):
            return None
        return f"{image} is not pinned to a Postgres release such as 16.16 or 17.12-alpine"
    if PATCH_TAG.search(tag):
        return None
    return f"{image} is not pinned to a major.minor.patch tag"


def depends_on_names(text: str) -> list[str]:
    names: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^([ \t]*)depends_on:[ \t]*$", line)
        if not match:
            index += 1
            continue
        indent = len(match.group(1))
        index += 1
        while index < len(lines):
            current = lines[index]
            if not current.strip() or current.strip().startswith("#"):
                index += 1
                continue
            current_indent = len(current) - len(current.lstrip(" "))
            if current_indent <= indent:
                break
            service = re.match(r"^[ \t]*([A-Za-z0-9_-]+):[ \t]*$", current)
            if service and current_indent == indent + 2:
                names.append(service.group(1))
            index += 1
    return names


def code(path: Path) -> str:
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def problems() -> list[str]:
    errors: list[str] = []
    names = NAMES.read_text(encoding="utf-8")
    marketing_raw = COMPOSE.read_text(encoding="utf-8")
    marketing = uncommented(marketing_raw)
    public = uncommented(PUBLIC.read_text(encoding="utf-8"))
    dockerfile = uncommented(DOCKERFILE.read_text(encoding="utf-8"))
    for label, text in (("compose.marketing.yml", marketing_raw), ("compose.public-edge.yml", public), ("Dockerfile", dockerfile)):
        for image in images(text):
            reason = unpinned(image)
            if reason:
                errors.append(f"{label}: {reason}")
    if "external: true" not in marketing:
        errors.append("compose.marketing.yml must attach to the existing resto network as external")
    for name in depends_on_names(marketing):
        if name in PROTECTED:
            errors.append(f"compose.marketing.yml depends_on {name}, which is an existing service")
    if re.search(r"@postgres:", marketing):
        errors.append("compose.marketing.yml still points a database URL at the resto postgres service")
    if "resto-postgres" in marketing or "mem_limit" in marketing:
        errors.append("compose.marketing.yml must not name resto-postgres or set mem_limit")
    if "BIND_ADDR:-127.0.0.1" not in marketing:
        errors.append("published marketing ports must default to 127.0.0.1")
    if "127.0.0.1:${TEMPORAL_UI_PORT:-8085}:8080" not in marketing:
        errors.append("Temporal UI must stay bound to 127.0.0.1")

    up = code(UP)
    if "-f compose.yml" in up or '-f "$ROOT/compose.yml"' in up or "compose.yml -f" in up:
        errors.append("up-marketing.sh loads compose.yml")
    for line in up.splitlines():
        tokens = line.replace("\\", " ").split()
        if "postgres" in tokens or "n8n" in tokens:
            errors.append(f"up-marketing.sh names an existing service: {line.strip()}")
    if "docker rm" in up or "compose down" in up:
        errors.append("up-marketing.sh must not remove containers")
    if "--no-recreate" not in up:
        errors.append("up-marketing.sh must pass --no-recreate")
    if "compose.public-edge.yml" in up or "up-public-edge.sh" in up:
        errors.append("up-marketing.sh must not start the public edge")
    if "docker network create" in up:
        errors.append("up-marketing.sh must not create a Docker network")
    if "marketing-guard.sh" not in up:
        errors.append("up-marketing.sh must guard the production resto tree")
    if '"${SERVICES[@]}"' not in up:
        errors.append("up-marketing.sh must start only the selected stage services")
    services = set(re.findall(r"(?m)^  ([a-z0-9-]+):$", marketing_raw))
    for array_name in ("STAGE_MAUTIC_SERVICES", "STAGE_POSTIZ_SERVICES", "STAGE_DASHBOARD_SERVICES"):
        match = re.search(rf"{array_name}=\((.*?)\)", names, re.S)
        if not match:
            errors.append(f"marketing-names.sh is missing {array_name}")
            continue
        for service in re.findall(r"[A-Za-z0-9_-]+", match.group(1)):
            if service in PROTECTED or service not in services:
                errors.append(f"{array_name} includes {service}, which is not a new marketing service")
    for line in marketing.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        if not any(token in stripped for token in ("/var/lib/", "/var/www/", ":/data", ":/config", ":/uploads")):
            continue
        if not any(bit in stripped for bit in ("/mautic/", "/postiz/", "/temporal/", "/command:", "/caddy/")):
            errors.append(f"volume is outside marketing data: {stripped}")
    setup = code(SETUP)
    if "docker rm" in setup or "docker compose" in setup or "compose up" in setup:
        errors.append("setup.sh must not remove or start containers")
    if "resto-postgres" not in names or "resto-n8n" not in names:
        errors.append("marketing-names.sh dropped a protected container")
    if "resto-postgres" in names.split("MARKETING_CONTAINERS", 1)[1].split("PROTECTED_CONTAINERS", 1)[0]:
        errors.append("resto-postgres is listed as a marketing container")
    return errors


def main() -> int:
    errors = problems()
    if errors:
        print("\n".join(errors))
        return 1
    print("Marketing compose is pinned and does not depend on existing services.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
