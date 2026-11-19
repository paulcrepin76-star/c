#!/usr/bin/env bash
# Read-only Unraid inspection. Paste this on the server.
# It does not check out files, start containers, create networks, or change ZFS.
# The only file it writes is /tmp/unraid-marketing-inspect.txt.
set -u

exec > >(tee /tmp/unraid-marketing-inspect.txt) 2>&1

echo "READ ONLY. No git checkout, pull, reset, docker run, network create, compose, zfs, or sysctl."
echo "The only write is /tmp/unraid-marketing-inspect.txt."
date --iso-8601=seconds
hostname
echo

ROOT=/mnt/user/appdata/resto
echo "===== git working tree ====="
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT" status --short --branch
  echo "HEAD $(git -C "$ROOT" rev-parse HEAD)"
  git -C "$ROOT" branch -vv
  echo "--- unstaged ---"
  git -C "$ROOT" diff --stat
  echo "--- staged ---"
  git -C "$ROOT" diff --cached --stat
  echo "--- untracked ---"
  git -C "$ROOT" ls-files --others --exclude-standard
else
  echo "Not a git checkout: $ROOT"
  ls -ld "$ROOT" 2>&1 || true
fi
echo

echo "===== cpu and memory ====="
nproc
uptime
free -h
grep -E 'MemTotal|MemAvailable' /proc/meminfo
echo -n "vm.max_map_count="
cat /proc/sys/vm/max_map_count
echo

echo "===== addresses and routes ====="
ip -4 -o addr
echo "--- routes ---"
ip -4 route
echo "--- tailscale ---"
if command -v tailscale >/dev/null 2>&1; then
  tailscale ip -4 || true
else
  echo "tailscale command not found"
fi
echo

echo "===== listeners ====="
ss -ltn || netstat -ltn || true
echo

echo "===== containers ====="
docker ps -a --format '{{.Names}}	{{.Status}}	{{.Ports}}' || echo "docker ps failed"
echo

echo "===== docker networks ====="
docker network ls || true
echo "===== docker network inspect ====="
ids="$(docker network ls -q 2>/dev/null || true)"
if [ -n "$ids" ]; then
  # shellcheck disable=SC2086
  docker network inspect $ids || true
else
  echo "no docker networks"
fi
echo

echo "===== address pools ====="
docker info 2>/dev/null | awk 'BEGIN{p=0} /Default Address Pool/{p=1} p{print} p && /^[^ ]/{if(!/Default Address Pool/){exit}}' || true
echo "--- /etc/docker/daemon.json ---"
if [ -f /etc/docker/daemon.json ]; then
  sed -n '1,200p' /etc/docker/daemon.json
else
  echo "absent"
fi
echo "--- /boot/config/docker.cfg ---"
if [ -f /boot/config/docker.cfg ]; then
  sed -n '1,200p' /boot/config/docker.cfg
else
  echo "absent"
fi
echo

echo "===== storage ====="
echo "--- /boot/config/shares/appdata.cfg ---"
if [ -f /boot/config/shares/appdata.cfg ]; then
  sed -n '1,80p' /boot/config/shares/appdata.cfg
else
  echo "absent"
fi
echo "--- disks ---"
lsblk -d -o NAME,ROTA,TRAN,SIZE,TYPE,MODEL || true
echo "--- mounts ---"
findmnt -A -o TARGET,SOURCE,FSTYPE || true
echo "--- zpool ---"
if command -v zpool >/dev/null 2>&1; then
  zpool list || true
  zpool status || true
else
  echo "zpool command not found"
fi
echo "--- zfs ---"
if command -v zfs >/dev/null 2>&1; then
  zfs list -o name,mountpoint,recordsize,compression,sync,logbias,primarycache,atime || true
else
  echo "zfs command not found"
fi
echo "--- appdata paths ---"
for path in \
  /mnt/user/appdata/resto \
  /mnt/user/appdata/resto/mautic \
  /mnt/user/appdata/resto/postiz \
  /mnt/user/appdata/resto/temporal \
  /mnt/user/appdata/resto/command \
  /mnt/user/appdata/resto/caddy
do
  if [ -e "$path" ]; then
    ls -ld "$path"
    readlink -f "$path" || true
  else
    echo "absent $path"
  fi
done
echo "--- copies under /mnt ---"
find /mnt -maxdepth 5 -type d \( \
  -path '*/appdata/resto' -o \
  -path '*/appdata/resto/mautic' -o \
  -path '*/appdata/resto/postiz' -o \
  -path '*/appdata/resto/temporal' -o \
  -path '*/appdata/resto/command' -o \
  -path '*/appdata/resto/caddy' \
\) -print 2>/dev/null || true
echo
echo "END. Paste this whole transcript back. Nothing was started."
