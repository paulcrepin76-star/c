#!/usr/bin/env bash
# Re-attach FlareSolverr to the networks Kapowarr and Prowlarr use.
# The container is created on manga-net only; Unraid drops extra networks
# when the container is recreated.
set -euo pipefail

if ! command -v docker >/dev/null; then
  echo "docker not found"
  exit 1
fi

if ! docker inspect flaresolverr >/dev/null 2>&1; then
  echo "flaresolverr container is not installed"
  exit 1
fi

docker network connect kapowarr_default flaresolverr 2>/dev/null || true
docker network connect media-net flaresolverr 2>/dev/null || true
docker inspect flaresolverr --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
echo "FlareSolverr should answer at http://flaresolverr:8191 from Kapowarr and Prowlarr."
