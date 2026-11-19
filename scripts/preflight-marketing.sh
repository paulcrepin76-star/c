#!/usr/bin/env bash
# Prints what the marketing stack needs. Does not start containers or change the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

APPDATA="${APPDATA:-$ROOT/appdata}"
export APPDATA
echo "App data: $APPDATA"
echo
echo "Memory on this machine:"
free -h || true
echo
if command -v docker >/dev/null 2>&1; then
  echo "Container memory right now:"
  docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' 2>/dev/null || true
  echo
else
  echo "Docker is not available here, so container memory cannot be measured."
  echo
fi

python3 - <<'PY'
import os, shutil
path = os.environ.get("APPDATA", "appdata")
usage = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path) or ".")
free_gb = usage.free / (1024 ** 3)
print(f"Free space beside app data: {free_gb:.1f} GB")
if free_gb < 8:
    raise SystemExit("Need at least 8 GB free for images and databases. Nothing was started.")
if free_gb < 20:
    print("Warning: under 20 GB free. Mautic media and Postiz uploads will need more later.")
PY

map_count="$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)"
echo "vm.max_map_count=${map_count}"
if [ "${map_count}" -lt 262144 ]; then
  echo
  echo "Elasticsearch, which the official Postiz Temporal setup uses, needs vm.max_map_count=262144."
  echo "This script will not change the kernel. On Unraid, run this once and add it to /boot/config/go:"
  echo "  sysctl -w vm.max_map_count=262144"
  exit 2
fi

python3 - <<'PY'
import socket, subprocess
expected = {8084: "resto-mautic", 4007: "resto-postiz", 8090: "resto-command"}
owners = {}
try:
    listing = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"], text=True)
except (OSError, subprocess.CalledProcessError):
    listing = ""
for line in listing.splitlines():
    name, _, ports = line.partition("\t")
    for port, owner in expected.items():
        if f":{port}->" in ports:
            owners[port] = name
busy = []
for port, owner in expected.items():
    holder = owners.get(port)
    if holder and holder != owner:
        busy.append(f"{port} is already used by {holder}, not {owner}")
        continue
    if holder == owner:
        continue
    sock = socket.socket()
    try:
        taken = sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()
    if taken:
        busy.append(f"{port} is already accepting connections")
if busy:
    print("Port check:")
    print("\n".join(busy))
    raise SystemExit("Free those ports, or change MAUTIC_PORT, POSTIZ_PORT, and COMMAND_PORT. Nothing was started.")
print("Host ports 8084, 4007, and 8090 are free or already belong to this stack.")
PY

echo
echo "Plan for about 4 to 8 GB of additional resident memory once Mautic, Postiz,"
echo "Temporal, and Elasticsearch are actually running. No container memory cap is set;"
echo "a tight cap is more likely to kill a campaign send than to save RAM."
echo "Preflight finished. No container was started."
