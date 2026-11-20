#!/usr/bin/env bash
# Starts only resto-marketing-edge. Does not start the dashboard and does not recreate Mautic or Postiz.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

if [ "${MARKETING_PUBLIC_APPROVED:-0}" != "1" ]; then
  echo "Nothing was started. Public HTTPS is separate from the Tailscale dashboard."
  echo "Set PUBLIC_POSTIZ_HOST, PUBLIC_MAUTIC_HOST, and ACME_EMAIL, then run:"
  echo "  MARKETING_PUBLIC_APPROVED=1 ./scripts/up-public-edge.sh"
  exit 3
fi

if [ ! -f "$ROOT/.env" ]; then
  echo "No .env. Nothing was started."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

for key in PUBLIC_POSTIZ_HOST PUBLIC_MAUTIC_HOST ACME_EMAIL; do
  value="$(grep -E "^${key}=" "$ROOT/.env" | head -1 | cut -d= -f2- || true)"
  if [ -z "$value" ]; then
    echo "Refusing: ${key} is empty. Nothing was started."
    exit 1
  fi
done

for host in "$PUBLIC_POSTIZ_HOST" "$PUBLIC_MAUTIC_HOST"; do
  case "$host" in
    *:*)
      echo "Refusing: ${host} should be a DNS name, not an address with a port. Nothing was started."
      exit 1
      ;;
  esac
  if printf '%s' "$host" | grep -Eq '^[0-9.]+$'; then
    echo "Refusing: ${host} is an IP address. Public HTTPS needs a DNS name. Nothing was started."
    exit 1
  fi
done

if [ "$PUBLIC_POSTIZ_HOST" = "$PUBLIC_MAUTIC_HOST" ]; then
  echo "Refusing: Postiz and Mautic need two different hostnames. Nothing was started."
  exit 1
fi

if ! docker network inspect resto >/dev/null 2>&1; then
  echo "The resto network does not exist yet. Start the marketing stack first. Nothing was published."
  exit 1
fi

mkdir -p "${APPDATA:-$ROOT/appdata}/caddy/data" "${APPDATA:-$ROOT/appdata}/caddy/config"

echo "This publishes 80 and 443 for ${PUBLIC_POSTIZ_HOST} and ${PUBLIC_MAUTIC_HOST}."
echo "The dashboard port is not part of this file."
docker compose -f "$ROOT/compose.public-edge.yml" --profile public-edge up -d --no-recreate edge
echo "Edge container: resto-marketing-edge"
echo "Set POSTIZ_URL to https://${PUBLIC_POSTIZ_HOST} before connecting a social account."
echo "Set the Mautic site URL to https://${PUBLIC_MAUTIC_HOST} inside Mautic after the certificate is issued."
