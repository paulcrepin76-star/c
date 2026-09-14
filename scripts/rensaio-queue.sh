#!/usr/bin/env bash
# Run on Unraid as root. Shows or clears the Rensaio download queue.
# Does not rename series. Does not start Comicarr. Does not delete manga files.
set -euo pipefail

BASE="${RENSAIO_URL:-http://127.0.0.1:9833}"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi

cmd="${1:-status}"

metrics() {
  curl -sS --max-time 20 "$BASE/api/downloads/metrics"
}

status() {
  echo "metrics $(metrics | jq -c .)"
  curl -sS --max-time 20 "$BASE/api/downloads?status=Waiting&limit=500" | jq -c '{
    waiting: .totalCount,
    titles: ([.downloads[].title] | group_by(.) | map({title:.[0], n:length})),
    providers: ([.downloads[].provider] | group_by(.) | map({provider:.[0], n:length}))
  }'
}

clean() {
  ids="$(curl -sS --max-time 20 "$BASE/api/downloads?status=Waiting&limit=500" | jq -r '.downloads[].id')"
  n="$(printf '%s\n' "$ids" | grep -c . || true)"
  echo "waiting_to_delete=$n"
  ok=0
  fail=0
  for id in $ids; do
    code="$(
      curl -sS -o /tmp/rensaio-queue-del.out -w '%{http_code}' --max-time 15 \
        -X PATCH "$BASE/api/downloads?id=${id}&action=Delete" || echo err
    )"
    if [ "$code" = "200" ]; then
      ok=$((ok + 1))
    else
      fail=$((fail + 1))
      echo "delete_fail ${id} http=${code}"
    fi
  done
  echo "deleted_ok=$ok deleted_fail=$fail"
  echo "metrics $(metrics | jq -c .)"
}

case "$cmd" in
  status) status ;;
  clean) clean ;;
  *)
    echo "Usage: bash scripts/rensaio-queue.sh [status|clean]"
    exit 1
    ;;
esac
