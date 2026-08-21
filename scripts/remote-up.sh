#!/usr/bin/env bash
# Runs on Unraid after files are in /mnt/user/appdata/resto
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi

  BIN="$ROOT/.bin/docker-compose"
  mkdir -p "$ROOT/.bin"
  if [ ! -x "$BIN" ]; then
    echo "Docker Compose is not installed. Downloading a local binary ..."
    curl -fsSL -o "$BIN" "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64"
    chmod +x "$BIN"
  fi
  "$BIN" "$@"
}

compose up -d --build
echo
echo "Containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | head -n 1
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'resto|paperless|mealie|n8n|metabase' || docker ps
