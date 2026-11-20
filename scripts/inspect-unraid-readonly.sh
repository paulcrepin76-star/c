#!/usr/bin/env bash
# Read-only Unraid inspection. Paste this on the server.
# The child shell owns set -u and the tee redirection, so the interactive shell stays as it was.
# The only file written is /tmp/unraid-marketing-inspect.txt.
bash <<'UNRAID_INSPECT'
set -u
export GIT_OPTIONAL_LOCKS=0

exec > >(tee /tmp/unraid-marketing-inspect.txt) 2>&1

echo "READ ONLY. No checkout, pull, reset, container start, network create, storage change, or sysctl."
echo "The only write is /tmp/unraid-marketing-inspect.txt."
echo "GIT_OPTIONAL_LOCKS=${GIT_OPTIONAL_LOCKS}"
date --iso-8601=seconds
hostname
echo

ROOT=/mnt/user/appdata/resto
echo "===== git working tree ====="
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT" status --short --branch
  echo "HEAD $(git -C "$ROOT" rev-parse HEAD)"
  git -C "$ROOT" branch -vv
  echo "--- unstaged names ---"
  git -C "$ROOT" diff --stat
  echo "--- staged names ---"
  git -C "$ROOT" diff --cached --stat
  echo "--- untracked names ---"
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
echo "===== docker network subnets ====="
ids="$(docker network ls -q 2>/dev/null || true)"
if [ -n "$ids" ]; then
  # Names, drivers, subnets, and attached addresses only. Labels and options are omitted.
  # shellcheck disable=SC2086
  docker network inspect $ids --format 'network {{.Name}} driver {{.Driver}} scope {{.Scope}}
{{range .IPAM.Config}}subnet {{.Subnet}} gateway {{.Gateway}} range {{.IPRange}}
{{end}}{{range .Containers}}attached {{.Name}} {{.IPv4Address}}
{{end}}' || true
else
  echo "no docker networks"
fi
echo

echo "===== address pools ====="
docker info 2>/dev/null | awk 'BEGIN{p=0} /Default Address Pool/{p=1} p{print} p && /^[^ ]/{if(!/Default Address Pool/){exit}}' || true
echo "--- daemon address pools ---"
if [ -f /etc/docker/daemon.json ] && command -v python3 >/dev/null 2>&1; then
  python3 -c 'import json; d=json.load(open("/etc/docker/daemon.json")); p=d.get("default-address-pools"); print("default-address-pools="+json.dumps(p) if p else "default-address-pools absent; other daemon.json keys omitted")'
elif [ -f /etc/docker/daemon.json ]; then
  echo "daemon.json present; contents omitted. python3 is absent, so its address pools were not extracted."
else
  echo "daemon.json absent"
fi
echo "--- docker.cfg storage keys ---"
if [ -f /boot/config/docker.cfg ]; then
  grep -E '^(DOCKER_ENABLED|DOCKER_CUSTOM_NETWORKS|DOCKER_IMAGE_FILE|DOCKER_IMAGE_SIZE|DOCKER_APP_CONFIG_PATH)=' /boot/config/docker.cfg || echo "none of the storage keys were set"
else
  echo "docker.cfg absent"
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
UNRAID_INSPECT
