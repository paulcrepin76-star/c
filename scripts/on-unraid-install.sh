#!/usr/bin/env bash
# Run this ON Unraid as root (you are already root@lerouxfamily).
# Installs wine cellar / costing next to the Paperless you already have.
set -euo pipefail

TARGET_DIR="${UNRAID_DIR:-/mnt/user/appdata/resto}"
REPO_URL="https://github.com/paulcrepin76-star/c.git"

if [ ! -d /mnt/user ]; then
  echo "This script is meant to run on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi

mkdir -p "$(dirname "$TARGET_DIR")"

if [ -d "$TARGET_DIR/.git" ]; then
  echo "Updating $TARGET_DIR"
  git -C "$TARGET_DIR" pull --ff-only
elif [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/compose.yml" ]; then
  echo "$TARGET_DIR already has files; leaving them in place."
else
  echo "Downloading stack into $TARGET_DIR"
  if command -v git >/dev/null 2>&1; then
    git clone "$REPO_URL" "$TARGET_DIR"
  else
    curl -fsSL "https://github.com/paulcrepin76-star/c/archive/refs/heads/main.tar.gz" | tar -xz -C "$(dirname "$TARGET_DIR")"
    mv "$(dirname "$TARGET_DIR")/c-main" "$TARGET_DIR"
  fi
fi

cd "$TARGET_DIR"
chmod +x scripts/*.sh scripts/paperless/*.sh 2>/dev/null || chmod +x scripts/*.sh
./scripts/setup.sh
./scripts/remote-up.sh
