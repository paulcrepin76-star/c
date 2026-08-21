#!/usr/bin/env bash
# Paste on Unraid: bash /mnt/user/appdata/resto/scripts/fix-up.sh
# Or: curl -fsSL https://raw.githubusercontent.com/paulcrepin76-star/c/main/scripts/fix-up.sh | bash
set -euo pipefail

DIR=/mnt/user/appdata/resto
if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid as root@lerouxfamily, not on the Mac."
  exit 1
fi

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  curl -fsSL https://raw.githubusercontent.com/paulcrepin76-star/c/main/scripts/on-unraid-install.sh | bash
  exit 0
fi

cd "$DIR"
docker rm -f resto-mealie resto-paperless >/dev/null 2>&1 || true
chmod +x scripts/*.sh
./scripts/setup.sh
./scripts/remote-up.sh

echo
echo "Listening on this server:"
ss -lnt 2>/dev/null | grep -E ':(8088|8000|5678|3001)\s' || netstat -lnt 2>/dev/null | grep -E ':(8088|8000|5678|3001)\s' || true
echo
echo "Containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo
echo "Local wine cellar check:"
curl -fsS -m 5 http://127.0.0.1:8088/health || echo "resto-core is NOT answering on 8088 yet"
echo
echo "From the Mac (Tailscale must be on), open:"
echo "  http://100.116.48.120:8088"
echo "Do not use a phone or browser that is off Tailscale."
