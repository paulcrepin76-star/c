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
  echo
  echo "On a Mac that has never used SSH keys:"
  echo "  ssh-keygen -t ed25519 -N \"\" -f ~/.ssh/id_ed25519"
  echo "  ssh-copy-id -i ~/.ssh/id_ed25519.pub root@100.116.48.120"
  echo "  ./scripts/deploy-unraid.sh root@100.116.48.120"
  exit 1
fi

if ! ls "$HOME"/.ssh/id_*.pub >/dev/null 2>&1 && [ ! -f "$HOME/.ssh/config" ]; then
  echo "No SSH key found on this computer (ssh-copy-id: No identities found)."
  echo "Create one, then copy it to Unraid. Type the Unraid root password only in this terminal:"
  echo
  echo "  mkdir -p ~/.ssh && chmod 700 ~/.ssh"
  echo "  ssh-keygen -t ed25519 -N \"\" -f ~/.ssh/id_ed25519 -C \"$(whoami)@$(hostname)\""
  echo "  ssh-copy-id -i ~/.ssh/id_ed25519.pub ${TARGET}"
  echo "  ssh ${TARGET} 'echo ok'"
  echo
  echo "Then run this script again."
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
