#!/usr/bin/env bash
# Prints a Python 3.11+ interpreter. Uses the host when it exists.
# Otherwise unpacks a pinned CPython under this checkout's .tools directory.
# That download is not a system package and does not touch /usr.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
marketing_refuse_production "$ROOT"

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  command -v python3
  exit 0
fi

private="$ROOT/.tools/python/bin/python3"
if [ -x "$private" ]; then
  printf '%s\n' "$private"
  exit 0
fi

if [ "${MARKETING_PYTHON_FETCH:-0}" != "1" ]; then
  echo "Host python3 is missing. An approved marketing command unpacks a private CPython 3.12.12 into ${ROOT}/.tools." >&2
  echo "No system package is installed, and nothing was downloaded." >&2
  exit 1
fi

if [ "$(uname -m)" != "x86_64" ]; then
  echo "The private CPython build is pinned for x86_64. This machine is $(uname -m)." >&2
  exit 1
fi

url="https://github.com/astral-sh/python-build-standalone/releases/download/20260127/cpython-3.12.12+20260127-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
sha="1c9b8720a71f810a04352dc82667ebd7757a565f46e9a7770215a80049582184"
mkdir -p "$ROOT/.tools"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
echo "Downloading a private CPython into ${ROOT}/.tools. /usr is left alone." >&2
curl -fsSL "$url" -o "$tmp"
echo "${sha}  ${tmp}" | sha256sum -c -
tar -xzf "$tmp" -C "$ROOT/.tools"
if [ ! -x "$private" ]; then
  echo "The archive did not contain ${private}." >&2
  exit 1
fi
printf '%s\n' "$private"
