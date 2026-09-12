#!/usr/bin/env bash
# Run on Unraid as root. Searches Rensaio for the five main manga titles.
set -euo pipefail

BASE="${RENSAIO_URL:-http://127.0.0.1:9833}"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi

echo "auth $(curl -sS --max-time 20 "$BASE/api/auth/status" | jq -c '{hasUsers, authenticationEnabled}')"
echo "settings $(curl -sS --max-time 20 "$BASE/api/settings" | jq -c '{storageFolder, preferredLanguages, nsfwVisibility, isWizardSetupComplete}')"
echo "sources $(curl -sS --max-time 60 "$BASE/api/search/sources" | jq 'length')"

ok=0
for q in "Bleach" "MPD Psycho" "Naruto" "One Piece" "Shangri-La Frontier"; do
  tmp="$(mktemp)"
  code="$(
    curl -sS --max-time 180 -o "$tmp" -w '%{http_code}' --get \
      "$BASE/api/search" \
      --data-urlencode "keyword=${q}" \
      --data-urlencode "languages=en,fr" || echo err
  )"
  count="$(jq 'if type=="array" then length else 0 end' "$tmp" 2>/dev/null || echo 0)"
  titles="$(jq -r 'if type=="array" then [.[:5][] | (.title // .Title // .name // empty)] | .[] else empty end' "$tmp" 2>/dev/null | head -5)"
  echo "search ${q}: http=${code} count=${count}"
  if [ -n "$titles" ]; then
    printf '%s\n' "$titles" | sed 's/^/  - /'
    ok=$((ok + 1))
  fi
  rm -f "$tmp"
done
echo "found_queries=$ok"
test "$ok" -ge 5
