#!/usr/bin/env bash
# Copy the YoLink → Survey Cafe bridge into Home Assistant. Does not print secrets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APPDATA="${APPDATA:-/mnt/user/appdata/resto}"
HA_CONFIG="${HA_CONFIG:-$APPDATA/homeassistant}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
PACKAGE_SRC="$ROOT/house/homeassistant/packages/survey_cafe_fridges.yaml"

if [ ! -f "$PACKAGE_SRC" ]; then
  echo "Missing $PACKAGE_SRC" >&2
  exit 1
fi

mkdir -p "$HA_CONFIG/packages"

cfg="$HA_CONFIG/configuration.yaml"
if [ ! -f "$cfg" ]; then
  cat > "$cfg" <<'EOF'
default_config:

homeassistant:
  packages: !include_dir_named packages
EOF
elif ! grep -q "packages:" "$cfg"; then
  tmp="$(mktemp)"
  awk '
    BEGIN { done=0 }
    /^homeassistant:[[:space:]]*$/ && !done {
      print
      print "  packages: !include_dir_named packages"
      done=1
      next
    }
    { print }
    END {
      if (!done) {
        print ""
        print "homeassistant:"
        print "  packages: !include_dir_named packages"
      }
    }
  ' "$cfg" > "$tmp"
  mv "$tmp" "$cfg"
fi

cp "$PACKAGE_SRC" "$HA_CONFIG/packages/survey_cafe_fridges.yaml"

key=""
if [ -f "$ENV_FILE" ]; then
  key="$(awk -F= '/^RESTO_API_KEY=/{sub(/^[^=]+=/,""); print; exit}' "$ENV_FILE" | tr -d '\r' | sed 's/^["'\'']//; s/["'\'']$//')"
fi
if [ -z "$key" ] && [ -n "${RESTO_API_KEY:-}" ]; then
  key="$RESTO_API_KEY"
fi
if [ -z "$key" ]; then
  echo "RESTO_API_KEY is missing in $ENV_FILE" >&2
  exit 1
fi

secrets="$HA_CONFIG/secrets.yaml"
touch "$secrets"
tmp="$(mktemp)"
grep -vE '^(resto_api_key|resto_readings_url):' "$secrets" > "$tmp" || true
printf 'resto_readings_url: http://resto-core:8080/api/house/readings\nresto_api_key: %s\n' "$key" >> "$tmp"
mv "$tmp" "$secrets"
chmod 600 "$secrets"

if docker inspect resto-homeassistant >/dev/null 2>&1; then
  docker restart resto-homeassistant >/dev/null
  echo "Home Assistant restarted with the YoLink cellar bridge."
else
  echo "Package installed. Start Home Assistant with ./scripts/up-house.sh"
fi

echo "Name the YoLink temperature entity sensor.wine_cellar_temperature (or the matching fridge slug)."
echo "Fridges board: http://100.116.48.120:8088/house"
