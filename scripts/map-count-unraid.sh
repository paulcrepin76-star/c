#!/usr/bin/env bash
# Shows the Elasticsearch vm.max_map_count change and how to reverse it.
# Does not write the kernel or /boot/config/go unless MARKETING_MAP_COUNT_APPROVED=1.
set -euo pipefail

want=262144
previous=65530
current="$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo unreadable)"
go_file="/boot/config/go"
line="sysctl -w vm.max_map_count=${want}"

echo "vm.max_map_count=${current}"
echo "Elasticsearch needs ${want}. The value recorded before Phase 2 was ${previous}."
echo "This script does not change the kernel unless MARKETING_MAP_COUNT_APPROVED=1."
echo
echo "Apply only after a separate approval:"
echo "  ${line}"
echo "Make it survive an Unraid reboot by adding that exact line to ${go_file}."
echo "Unraid rebuilds /etc from the flash image. A line in /etc/sysctl.conf does not survive a reboot."
echo "Reverse the running value:"
echo "  sysctl -w vm.max_map_count=${previous}"
echo "Reverse the reboot setting by deleting that line from ${go_file}."
echo "Phase 2 does not call this script."

if [ "${MARKETING_MAP_COUNT_APPROVED:-0}" != "1" ]; then
  echo "Nothing was changed."
  exit 3
fi

sysctl -w "vm.max_map_count=${want}"
if [ ! -f "$go_file" ]; then
  echo "The running value is ${want}. ${go_file} is missing, so the change will not survive a reboot."
  exit 1
fi
if grep -qxF "$line" "$go_file"; then
  echo "Already present in ${go_file}."
else
  printf '\n%s\n' "$line" >> "$go_file"
  echo "Appended to ${go_file}."
fi
echo "vm.max_map_count=$(cat /proc/sys/vm/max_map_count)"
