#!/usr/bin/env bash
# Run on Unraid as root. Resumes the in-place Mylar3 import until the
# watchlist has the existing /comics library. Does not scan.
# Does not send imp_move. Does not touch manga. Does not start Comicarr.
# Mylar3 was removed. Do not reinstall unless asked.
set -euo pipefail

if [ "${MYLAR3_REINSTALL:-}" != "1" ]; then
  echo "Mylar3 was removed. Do not reinstall unless asked." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
IMPORT="$HERE/mylar3-import.sh"
MYLAR=/mnt/user/appdata/mylar3
COMICS=/mnt/user/media/book/comics
DB="$MYLAR/mylar/mylar.db"
LOG="$MYLAR/import-watch.log"
PIDFILE="$MYLAR/import-watch.pid"
SNAPSHOT=/tmp/comics-archives-before-resume.txt
UI_PORT=8090
IDLE_SECONDS="${IDLE_SECONDS:-480}"
LIMIT_WAIT="${LIMIT_WAIT:-3600}"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -x "$IMPORT" ]; then
  echo "Missing $IMPORT"
  exit 1
fi

if [ -f "$PIDFILE" ]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "${old:-}" ] && kill -0 "$old" 2>/dev/null; then
    echo "watch already running pid=$old"
    exit 0
  fi
fi
echo "$$" > "$PIDFILE"

log() {
  echo "$(date -Is) $*" | tee -a "$LOG"
}

sqlite_retry() {
  local sql="$1"
  local i
  for i in $(seq 1 8); do
    if sqlite3 "$DB" "$sql" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "lock"
}

flags_safe() {
  grep -q '^imp_move = False' "$MYLAR/mylar/config.ini" \
    && grep -q '^imp_rename = False' "$MYLAR/mylar/config.ini"
}

archive_count() {
  find "$COMICS" -type f \( -iname '*.cbz' -o -iname '*.cbr' -o -iname '*.cb7' -o -iname '*.cbt' \) | wc -l
}

import_busy() {
  docker logs --since 3m mylar3 2>&1 | grep -Eq 'Successfully imported|Attempting to add directly|Now adding/updating|FILE-RESCAN|getComic'
}

rate_limited() {
  docker logs --since 5m mylar3 2>&1 | grep -Eqi 'api limit|rate limit exceeded|slow down cowboy'
}

resume_import() {
  if ! flags_safe; then
    log "unsafe flags; refusing resume"
    return 1
  fi
  log "resume massimport"
  curl -sS -o /tmp/mylar3-massimport.out -w "massimport_http=%{http_code}\n" --max-time 60 \
    --get --data-urlencode "action=massimport" \
    "http://127.0.0.1:${UI_PORT}/markImports" | tee -a "$LOG" || true
}

seed_remaining() {
  if ! flags_safe; then
    log "unsafe flags; refusing remaining"
    return 1
  fi
  log "seed remaining folders"
  bash "$IMPORT" remaining >> "$LOG" 2>&1 || log "remaining failed"
}

log "watch start pid=$$"
before="$(archive_count)"
if [ -f "$SNAPSHOT" ]; then
  snap="$(wc -l < "$SNAPSHOT" | tr -d ' ')"
  log "archives=$before snapshot=$snap"
else
  find "$COMICS" -type f \( -iname '*.cbz' -o -iname '*.cbr' -o -iname '*.cb7' -o -iname '*.cbt' \) | sort > "$SNAPSHOT"
  log "wrote snapshot archives=$before"
fi

idle_since="$(date +%s)"
remaining_seeded=0

while true; do
  if ! flags_safe; then
    log "imp_move or imp_rename is on; stopping watch"
    break
  fi
  now_count="$(archive_count)"
  if [ "$now_count" != "$before" ]; then
    log "archive count changed $before -> $now_count; stopping watch"
    break
  fi
  comics="$(sqlite_retry "SELECT COUNT(*) FROM comics;")"
  stamped="$(sqlite_retry "SELECT COUNT(DISTINCT ComicID) FROM importresults WHERE Status='Not Imported' AND ComicID IS NOT NULL AND ComicID!='' AND ComicID!='None';")"
  groups="$(sqlite_retry "SELECT COUNT(*) FROM (SELECT 1 FROM importresults WHERE Status='Not Imported' GROUP BY DynamicName, Volume);")"
  log "comics=$comics remaining_stamped=$stamped remaining_groups=$groups busy=$(import_busy && echo yes || echo no)"

  if rate_limited && ! import_busy; then
    log "comicvine rate limited; waiting ${LIMIT_WAIT}s"
    sleep "$LIMIT_WAIT"
    idle_since="$(date +%s)"
    resume_import
    continue
  fi

  if import_busy; then
    idle_since="$(date +%s)"
    sleep 60
    continue
  fi

  idle=$(( $(date +%s) - idle_since ))
  if [ "$stamped" != "lock" ] && [ "${stamped:-0}" -gt 0 ] && [ "$idle" -ge "$IDLE_SECONDS" ]; then
    resume_import
    idle_since="$(date +%s)"
    sleep 90
    continue
  fi

  if [ "$stamped" = "0" ] && [ "$remaining_seeded" = "0" ] && [ "$idle" -ge "$IDLE_SECONDS" ]; then
    remaining_seeded=1
    seed_remaining
    idle_since="$(date +%s)"
    continue
  fi

  if [ "$stamped" = "0" ] && [ "$groups" = "0" ] && [ "$remaining_seeded" = "1" ]; then
    log "import queue empty comics=$comics archives=$now_count"
    break
  fi

  if [ "$groups" != "lock" ] && [ "${groups:-0}" -gt 0 ] && [ "$stamped" = "0" ] && [ "$idle" -ge "$IDLE_SECONDS" ]; then
    resume_import
    idle_since="$(date +%s)"
  fi
  sleep 60
done

if [ -d "$COMICS/.zzz_check" ] && [ -z "$(ls -A "$COMICS/.zzz_check" 2>/dev/null || true)" ]; then
  rmdir "$COMICS/.zzz_check"
  log "removed_empty_mylar_write_test=yes"
fi

rm -f "$PIDFILE"
log "watch exit"
