#!/usr/bin/env bash
# Fills marketing secrets that are missing or still placeholders.
# Prints key names only. Does not print values and does not touch existing passwords.
fill_marketing_secrets() {
  local file="$1"
  [ -f "$file" ] || return 0
  local key bytes current value
  while IFS='|' read -r key bytes; do
    [ -n "$key" ] || continue
    current="$(grep -E "^${key}=" "$file" | head -1 | cut -d= -f2- || true)"
    case "$current" in
      ""|change-me|change-me-*)
        value="$(openssl rand -hex "$bytes")"
        python3 - "$file" "$key" "$value" <<'PY'
import sys
path, key, value = sys.argv[1:]
lines = open(path, encoding="utf-8").read().splitlines()
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
        echo "Set ${key} in .env"
        ;;
    esac
  done <<'KEYS'
MAUTIC_DB_ROOT_PASSWORD|24
MAUTIC_DB_PASSWORD|24
POSTIZ_DB_PASSWORD|24
POSTIZ_JWT_SECRET|32
TEMPORAL_DB_PASSWORD|24
COMMAND_SECRET_KEY|32
COMMAND_ADMIN_PASSWORD|18
KEYS

  if ! grep -q "^COMMAND_ADMIN_EMAIL=" "$file"; then
    echo "COMMAND_ADMIN_EMAIL=surveycafedowntown@gmail.com" >> "$file"
    echo "Set COMMAND_ADMIN_EMAIL in .env"
  fi
}
