#!/usr/bin/env bash
# Start Home Assistant + Frigate only. Does not touch Paperless or Mealie.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  docker-compose "$@"
}

mkdir -p "${APPDATA:-/mnt/user/appdata/resto}/homeassistant"
mkdir -p "${APPDATA:-/mnt/user/appdata/resto}/frigate/config"
mkdir -p "${APPDATA:-/mnt/user/appdata/resto}/frigate/media"
mkdir -p "${APPDATA:-/mnt/user/appdata/resto}/mosquitto"
cp -n "$ROOT/house/frigate.yml" "${APPDATA:-/mnt/user/appdata/resto}/frigate/config/config.yml" 2>/dev/null || true
if [ ! -f "${APPDATA:-/mnt/user/appdata/resto}/frigate/config/config.yml" ]; then
  cp "$ROOT/house/frigate.yml" "${APPDATA:-/mnt/user/appdata/resto}/frigate/config/config.yml"
fi

compose up -d --no-deps mosquitto homeassistant frigate

# Homepage (port 3000, "Leroux Family") — append House tiles if the file exists.
for candidate in \
  /mnt/user/appdata/homepage/config/services.yaml \
  /mnt/user/appdata/homepage/services.yaml \
  /mnt/user/appdata/gethomepage/config/services.yaml
do
  if [ -f "$candidate" ] && ! grep -q "Home Assistant" "$candidate"; then
    printf '\n' >> "$candidate"
    cat "$ROOT/homepage/services-house.yaml" >> "$candidate"
    echo "Added House tiles to $candidate"
  fi
done

echo
echo "Home Assistant: http://100.116.48.120:8123"
echo "Frigate:        http://100.116.48.120:8971"
echo "Cellar house:   http://100.116.48.120:8088/house"
echo "Homarr:         http://100.116.48.120:7575  (add the same two app tiles if the board is empty)"
