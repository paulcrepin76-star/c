#!/usr/bin/env bash
# Restores the original /boot/config/go saved by scripts/map-count-unraid.sh.
# The running kernel value is changed only after that restore has been verified.
set -euo pipefail

want_fallback=65530
go_file="${MARKETING_GO_FILE:-/boot/config/go}"
proc_file="${MARKETING_MAP_COUNT_PROC:-/proc/sys/vm/max_map_count}"
backup_file="${MARKETING_MAP_COUNT_BACKUP:-${go_file}.pre-marketing-mapcount}"
meta_file="${backup_file}.meta"

echo "Rollback restores ${backup_file} over ${go_file}."
echo "The running vm.max_map_count is changed only after the restored boot file matches that backup."
echo "This does nothing unless MARKETING_MAP_COUNT_ROLLBACK_APPROVED=1."

if [ "${MARKETING_MAP_COUNT_ROLLBACK_APPROVED:-0}" != "1" ]; then
  echo "Nothing was changed."
  exit 3
fi

if [ -L "$go_file" ] || [ -L "$backup_file" ] || [ -L "$proc_file" ]; then
  echo "Refusing: a boot path is a symlink. Nothing was changed."
  exit 1
fi
if [ ! -f "$backup_file" ]; then
  echo "Refusing: ${backup_file} is missing. Nothing was changed."
  exit 1
fi
if [ ! -f "$meta_file" ]; then
  echo "Refusing: ${meta_file} is missing. Nothing was changed."
  exit 1
fi

runtime="$(awk -F= '/^runtime=/{print $2; exit}' "$meta_file")"
if ! printf '%s\n' "$runtime" | grep -Eq '^[0-9]+$'; then
  echo "Refusing: the saved runtime value is not a number. Nothing was changed."
  exit 1
fi

mode="$(stat -c '%a' "$backup_file")"
tmp="$(mktemp "${go_file}.tmp.XXXXXX")"
cp -p "$backup_file" "$tmp"
mv -f "$tmp" "$go_file"
chmod "$mode" "$go_file"
if ! cmp -s "$backup_file" "$go_file"; then
  echo "Refusing: ${go_file} does not match the backup after restore. The kernel was not changed."
  exit 1
fi
echo "Restored the original boot file ${go_file}."

sysctl -w "vm.max_map_count=${runtime}"
now="$(tr -d '[:space:]' < "$proc_file")"
if [ "$now" != "$runtime" ]; then
  echo "The boot file was restored. The running vm.max_map_count is ${now}, not ${runtime}."
  exit 1
fi
echo "Running vm.max_map_count=${now}."
if [ "$runtime" != "$want_fallback" ]; then
  echo "The saved runtime value is ${runtime}."
fi
