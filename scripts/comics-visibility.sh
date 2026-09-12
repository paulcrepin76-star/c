#!/usr/bin/env bash
# Run on Unraid (root@lerouxfamily) to see why Kapowarr misses files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"

if [ "${1:-}" = "--fixture" ] || [ -d /mnt/user ]; then
  exec python3 "$ROOT/scripts/comics_visibility.py" "$@"
fi

echo "Not on Unraid. Replaying the last saved snapshot from lerouxfamily."
exec python3 "$ROOT/scripts/comics_visibility.py" --fixture "$ROOT/scripts/tests/fixtures/leroux-comics.json" "$@"
