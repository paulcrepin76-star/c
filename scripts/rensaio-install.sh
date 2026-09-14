#!/usr/bin/env bash
# Run on Unraid as root. Stops Comicarr and starts Rensaio for manga grabs.
# Does not move or delete manga files Kavita already reads.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_SRC="$HERE/../docker/comics/compose.rensaio.yml"
COMICARR=/mnt/user/appdata/comicarr
RENSAIO=/mnt/user/appdata/rensaio
MANGA=/mnt/user/media/book/manga
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$COMPOSE_SRC" ]; then
  echo "Missing $COMPOSE_SRC"
  exit 1
fi
if [ ! -d "$MANGA" ]; then
  echo "Manga folder not found at $MANGA"
  exit 1
fi

mkdir -p "$RENSAIO/config" "$RENSAIO/manual-backups"
cp -a "$COMPOSE_SRC" "$RENSAIO/compose.yml"
chown -R 99:100 "$RENSAIO"

if docker inspect comicarr >/dev/null 2>&1; then
  echo "Stopping Comicarr (container only; manga files stay)."
  if [ -f "$COMICARR/compose.yml" ]; then
    cp -a "$COMICARR/compose.yml" "$RENSAIO/manual-backups/comicarr-compose-$STAMP.yml"
    (cd "$COMICARR" && docker compose down --remove-orphans) || true
  fi
  docker stop comicarr >/dev/null 2>&1 || true
  docker rm comicarr >/dev/null 2>&1 || true
fi
if [ -d "$COMICARR" ] && [ ! -e "/mnt/user/appdata/comicarr-backup-$STAMP" ]; then
  mv "$COMICARR" "/mnt/user/appdata/comicarr-backup-$STAMP"
  echo "Comicarr appdata kept at /mnt/user/appdata/comicarr-backup-$STAMP"
fi

cd "$RENSAIO"
docker compose pull
docker compose up -d

code=000
for _ in $(seq 1 90); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:9833/ || true)"
  if [ "$code" = "200" ]; then
    break
  fi
  sleep 2
done
echo "rensaio_http=$code"
if [ "$code" = "200" ] && command -v jq >/dev/null 2>&1; then
  raw="$(mktemp)"
  out="$(mktemp)"
  trap 'rm -f "$raw" "$out"' RETURN
  curl -sS --max-time 20 http://127.0.0.1:9833/api/settings > "$raw"
  # Skip the import wizard so it cannot rewrite Kavita folders. Search/subscribe instead.
  jq '.preferredLanguages = ["en","fr"]
      | .nsfwVisibility = "Show"
      | .isWizardSetupComplete = true
      | .flareSolverrEnabled = true
      | .flareSolverrUrl = "http://flaresolverr:8191"
      | .flareSolverrAsResponseFallback = true' "$raw" > "$out"
  curl -sS --max-time 20 -X PUT -H "Content-Type: application/json" --data-binary @"$out" \
    http://127.0.0.1:9833/api/settings >/dev/null || true
  echo "preferred_languages=en,fr nsfw=Show wizard=complete"
  # Wizard "install-extensions" only covers already-imported series. Install
  # the usual community indexes plus official English publishers.
  for pkg in \
    eu.kanade.tachiyomi.extension.all.mangadex \
    eu.kanade.tachiyomi.extension.all.mangafire \
    eu.kanade.tachiyomi.extension.all.mangaplus \
    eu.kanade.tachiyomi.extension.en.weebcentral \
    eu.kanade.tachiyomi.extension.en.vizshonenjump \
    eu.kanade.tachiyomi.extension.all.webtoons \
    eu.kanade.tachiyomi.extension.en.kodansha \
    eu.kanade.tachiyomi.extension.en.inkr \
    eu.kanade.tachiyomi.extension.en.tapastic
  do
    curl -sS --max-time 180 -o /dev/null -w "install_${pkg##*.}=%{http_code}\n" \
      -X POST "http://127.0.0.1:9833/api/provider/install/${pkg}" || true
  done
fi
echo "UI: http://100.116.48.120:9833"
echo "Series path: $MANGA -> /series"
echo "Do not use Rename on folders Kavita already reads."
