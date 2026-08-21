#!/usr/bin/env bash
# Copy this repo onto Unraid over SSH and start the stack.
# Run this from a computer that can already: ssh root@YOUR_UNRAID
#
#   ./scripts/deploy-unraid.sh root@192.168.1.50
#   UNRAID_SSH=root@tower ./scripts/deploy-unraid.sh
#
# Do not put the Unraid root password in git or in a chat. Use a key:
#   ssh-copy-id root@192.168.1.50
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-${UNRAID_SSH:-}}"
REMOTE_DIR="${UNRAID_DIR:-/mnt/user/appdata/resto}"

if [ -z "$TARGET" ]; then
  echo "Usage: $0 root@UNRAID_IP"
  echo
  echo "This script must run on a machine that already reaches Unraid."
  echo "A Cursor cloud agent cannot see 192.168.x.x unless you use Tailscale/WireGuard."
  echo
  echo "Example:"
  echo "  ssh-copy-id root@192.168.1.50"
  echo "  ./scripts/deploy-unraid.sh root@192.168.1.50"
  exit 1
fi

echo "Checking SSH to ${TARGET} ..."
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$TARGET" 'test -d /mnt/user && command -v docker >/dev/null'; then
  echo
  echo "Cannot SSH as ${TARGET} (or Docker / /mnt/user is missing)."
  echo "Fix on your laptop:"
  echo "  ssh-copy-id ${TARGET}"
  echo "  ssh ${TARGET} 'ls /mnt/user && docker info >/dev/null && echo ok'"
  exit 1
fi

echo "Syncing to ${TARGET}:${REMOTE_DIR}"
ssh "$TARGET" "mkdir -p '${REMOTE_DIR}'"
rsync -az --delete \
  --exclude '.git/' \
  --exclude 'appdata/' \
  --exclude '.env' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.pyc' \
  "$ROOT/" "${TARGET}:${REMOTE_DIR}/"

echo "Starting stack on Unraid ..."
ssh "$TARGET" "REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"
chmod +x scripts/setup.sh scripts/remote-up.sh
./scripts/setup.sh
./scripts/remote-up.sh
REMOTE

echo
echo "Deploy finished. On your LAN open http://$(echo "$TARGET" | sed 's/.*@//'):8088"
