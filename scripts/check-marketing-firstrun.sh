#!/usr/bin/env bash
# Sources a fresh copy of .env.example in an isolated shell and validates compose config.
# Does not write a checkout .env, start a container, or touch the production tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$ROOT/.env.example" "$tmp/.env"
chmod 600 "$tmp/.env"

data_root="/mnt/cache/appdata/surveycafe-marketing"
snapshot_dirs() {
  if [ -d "$data_root" ]; then
    find "$data_root" -type d | LC_ALL=C sort
  fi
}
snapshot_dirs > "$tmp/dirs-before"

env -i PATH="$PATH" HOME="$tmp" bash --noprofile --norc -c '
set -euo pipefail
set -a
source "$1"
set +a
test "$HOME_MARKET" = "Bonita Springs, Florida"
test "$APPDATA" = "/mnt/cache/appdata/surveycafe-marketing"
test "$BIND_ADDR" = "100.116.48.120"
test "$HOME_LON" = "-81.7787"
test "$COMMAND_ADMIN_EMAIL" = "surveycafedowntown@gmail.com"
test "$MAUTIC_TRUSTED_PROXIES" = "[]"
printf "%s\n" "Sourced a fresh .env.example in an isolated shell."
' bash "$tmp/.env"

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is not available. Nothing was started."
  exit 1
fi

docker compose \
  --env-file "$tmp/.env" \
  --project-directory "$ROOT" \
  -f "$ROOT/compose.marketing.yml" \
  --profile marketing \
  config --format json > "$tmp/config.json"

py="$("$ROOT/scripts/ensure-private-python.sh")"
"$py" - "$ROOT/.env.example" "$tmp/config.json" <<'PY'
import json
import re
import sys
from pathlib import Path

example = Path(sys.argv[1])
unsafe = re.compile(r"[\s$`\\!#;&|<>(){}*?\[\]]")
for line in example.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :]
    if "=" not in stripped:
        raise SystemExit(f"Not an assignment: {stripped}")
    key, raw = stripped.split("=", 1)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise SystemExit(f"Bad env key: {key}")
    quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
    if raw != "" and not quoted and unsafe.search(raw):
        raise SystemExit(f"{key} must be quoted before this file is sourced")

doc = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
services = doc["services"]
for name in ("mautic", "mautic-mysql", "mautic-cron", "mautic-worker"):
    if name not in services:
        raise SystemExit(f"Compose config is missing {name}")
for banned in ("postgres", "n8n", "paperless", "mealie", "homeassistant", "frigate"):
    if banned in services:
        raise SystemExit(f"Compose config includes existing service {banned}")
sources = [item.get("source", "") for item in services["mautic"].get("volumes") or []]
if not any(item.startswith("/mnt/cache/appdata/surveycafe-marketing/mautic/") for item in sources):
    raise SystemExit(f"Mautic volumes are not under the marketing data path: {sources}")
if any("/mnt/cache/appdata/resto" in item or "/mnt/user/appdata/resto" in item for item in sources):
    raise SystemExit(f"Mautic volumes point at the production tree: {sources}")
resto = (doc.get("networks") or {}).get("resto") or {}
if resto.get("external") is not True or resto.get("name") != "resto":
    raise SystemExit("Compose config does not join the existing resto network")
ports = services["mautic"].get("ports") or []
if not any(str(item.get("published")) == "8084" and item.get("host_ip") == "100.116.48.120" for item in ports):
    raise SystemExit(f"Mautic is not published on the Tailscale address: {ports}")
proxies = (services["mautic"].get("environment") or {}).get("MAUTIC_TRUSTED_PROXIES")
try:
    parsed = json.loads(proxies)
except json.JSONDecodeError as exc:
    raise SystemExit(f"MAUTIC_TRUSTED_PROXIES is not JSON: {exc}") from exc
if parsed != []:
    raise SystemExit(f"MAUTIC_TRUSTED_PROXIES must be an empty JSON array for direct Tailscale access: {proxies!r}")
print("MAUTIC_TRUSTED_PROXIES is [].")
print("Compose config validated for the Mautic service. No container was started.")
PY

snapshot_dirs > "$tmp/dirs-after"
if ! cmp -s "$tmp/dirs-before" "$tmp/dirs-after"; then
  echo "Refusing: compose config created marketing data. That was not supposed to happen."
  diff -u "$tmp/dirs-before" "$tmp/dirs-after" || true
  exit 1
fi
if [ -s "$tmp/dirs-before" ]; then
  echo "Marketing data directory already existed. Compose config did not add directories."
fi
echo "First-run env and compose check finished. No container was started."
