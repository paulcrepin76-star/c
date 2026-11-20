#!/usr/bin/env bash
# Inspects Unraid's /boot/config/go and, only with approval, makes vm.max_map_count survive a reboot.
# The boot file is backed up and checked before the running kernel value is changed.
# Phase 2 does not call this script.
set -euo pipefail

want=262144
fallback_previous=65530
go_file="${MARKETING_GO_FILE:-/boot/config/go}"
proc_file="${MARKETING_MAP_COUNT_PROC:-/proc/sys/vm/max_map_count}"
backup_file="${MARKETING_MAP_COUNT_BACKUP:-${go_file}.pre-marketing-mapcount}"
meta_file="${backup_file}.meta"
canonical="sysctl -w vm.max_map_count=${want}"

if [ -L "$proc_file" ]; then
  echo "Refusing: ${proc_file} is a symlink. Nothing was changed."
  exit 1
fi
if [ -f "$proc_file" ]; then
  current="$(tr -d '[:space:]' < "$proc_file")"
else
  current="unreadable"
fi

echo "vm.max_map_count=${current}"
echo "Elasticsearch needs ${want}. The value recorded before Phase 2 was ${fallback_previous}."
echo "Boot file: ${go_file}"
echo "This script does not change the kernel unless MARKETING_MAP_COUNT_APPROVED=1."
echo "It inspects ${go_file} before any write. A backup is stored at ${backup_file}."
echo "Rollback restores that backup:"
echo "  MARKETING_MAP_COUNT_ROLLBACK_APPROVED=1 ./scripts/map-count-rollback.sh"
echo "Unraid rebuilds /etc from the flash image. A line in /etc/sysctl.conf does not survive a reboot."
echo "Phase 2 does not call this script."

strip_unquoted_comment() {
  local line="$1"
  local i char
  local out=""
  local single=0
  local double=0
  local len=${#line}
  for ((i = 0; i < len; i++)); do
    char="${line:i:1}"
    if [ "$char" = "'" ] && [ "$double" -eq 0 ]; then
      if [ "$single" -eq 0 ]; then single=1; else single=0; fi
      out+="$char"
      continue
    fi
    if [ "$char" = '"' ] && [ "$single" -eq 0 ]; then
      if [ "$double" -eq 0 ]; then double=1; else double=0; fi
      out+="$char"
      continue
    fi
    if [ "$char" = '#' ] && [ "$single" -eq 0 ] && [ "$double" -eq 0 ]; then
      break
    fi
    if [ "$char" = '\' ] && [ "$single" -eq 0 ]; then
      out+="$char"
      i=$((i + 1))
      if [ "$i" -lt "$len" ]; then
        out+="${line:i:1}"
      fi
      continue
    fi
    out+="$char"
  done
  printf '%s' "$out"
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

is_simple_map_count() {
  local code="$1"
  [[ "$code" =~ ^sysctl[[:space:]]+-w[[:space:]]+vm\.max_map_count=[\'\"]?([0-9]+)[\'\"]?$ ]] && return 0
  [[ "$code" =~ ^echo[[:space:]]+[\'\"]?([0-9]+)[\'\"]?[[:space:]]+\>+[[:space:]]*/proc/sys/vm/max_map_count$ ]] && return 0
  return 1
}

simple_map_value() {
  local code="$1"
  if [[ "$code" =~ ^sysctl[[:space:]]+-w[[:space:]]+vm\.max_map_count=[\'\"]?([0-9]+)[\'\"]?$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$code" =~ ^echo[[:space:]]+[\'\"]?([0-9]+)[\'\"]?[[:space:]]+\>+[[:space:]]*/proc/sys/vm/max_map_count$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

has_flow_stop() {
  local code="$1"
  [[ "$code" =~ ^(exit|return)([[:space:]]|$) ]] && return 0
  [[ "$code" =~ (^|[;&]|\&\&|\|\|)[[:space:]]*(exit|return)([[:space:]]|$) ]] && return 0
  return 1
}

heredoc_delim() {
  local code="$1"
  if [[ "$code" =~ \<\<\-[[:space:]]*[\'\"]([A-Za-z0-9_]+)[\'\"] ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$code" =~ \<\<\-[[:space:]]*([A-Za-z0-9_]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$code" =~ \<\<[[:space:]]*[\'\"]([A-Za-z0-9_]+)[\'\"] ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$code" =~ \<\<[[:space:]]*([A-Za-z0-9_]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

# Prints one audit line per input file: complex, barriers, simple values.
# Exit 0 when the file can be edited. Exit 2 when a vm.max_map_count use is not a whole-line setting.
audit_go() {
  local src="$1"
  local heredoc=""
  local line_no=0
  local raw code trimmed delim
  local complex=0
  local barriers=""
  local values=""
  local simple_at=""
  while IFS= read -r raw || [ -n "$raw" ]; do
    line_no=$((line_no + 1))
    if [ -n "$heredoc" ]; then
      trimmed="$(trim "$raw")"
      if [ "$trimmed" = "$heredoc" ]; then
        heredoc=""
      fi
      continue
    fi
    if [[ "$raw" =~ ^#! ]]; then
      continue
    fi
    code="$(trim "$(strip_unquoted_comment "$raw")")"
    if [ -z "$code" ]; then
      continue
    fi
    if delim="$(heredoc_delim "$code")"; then
      heredoc="$delim"
    elif [[ "$code" == *"<<"* ]]; then
      echo "complex=1"
      echo "reason=unparsed-heredoc"
      return 2
    fi
    if [[ "$code" == *"vm.max_map_count"* ]]; then
      if is_simple_map_count "$code"; then
        values="${values}$(simple_map_value "$code") "
        simple_at="${simple_at}${line_no} "
      else
        complex=1
      fi
    fi
    if has_flow_stop "$code"; then
      barriers="${barriers}${line_no} "
    fi
  done < "$src"
  echo "complex=${complex}"
  echo "barriers=${barriers}"
  echo "values=${values}"
  echo "simple_at=${simple_at}"
  if [ "$complex" -ne 0 ]; then
    return 2
  fi
  return 0
}

rebuild_go() {
  local src="$1"
  local dest="$2"
  local heredoc=""
  local raw code trimmed delim
  local inserted=0
  : > "$dest"
  while IFS= read -r raw || [ -n "$raw" ]; do
    if [ -n "$heredoc" ]; then
      printf '%s\n' "$raw" >> "$dest"
      trimmed="$(trim "$raw")"
      if [ "$trimmed" = "$heredoc" ]; then
        heredoc=""
      fi
      continue
    fi
    if [[ "$raw" =~ ^#! ]] || [[ "$raw" =~ ^[[:space:]]*# ]] || [ -z "$(trim "$raw")" ]; then
      printf '%s\n' "$raw" >> "$dest"
      continue
    fi
    code="$(trim "$(strip_unquoted_comment "$raw")")"
    if [ -z "$code" ]; then
      printf '%s\n' "$raw" >> "$dest"
      continue
    fi
    if delim="$(heredoc_delim "$code")"; then
      heredoc="$delim"
    fi
    if is_simple_map_count "$code"; then
      continue
    fi
    if [ "$inserted" -eq 0 ]; then
      printf '%s\n' "$canonical" >> "$dest"
      inserted=1
    fi
    printf '%s\n' "$raw" >> "$dest"
  done < "$src"
  if [ "$inserted" -eq 0 ]; then
    printf '%s\n' "$canonical" >> "$dest"
  fi
}

persistent_ok() {
  local src="$1"
  local audit complex barriers values simple_at first_simple first_barrier
  if ! audit="$(audit_go "$src")"; then
    return 1
  fi
  complex="$(printf '%s\n' "$audit" | awk -F= '/^complex=/{print $2}')"
  barriers="$(printf '%s\n' "$audit" | awk -F= '/^barriers=/{print substr($0, index($0, "=") + 1)}')"
  values="$(printf '%s\n' "$audit" | awk -F= '/^values=/{print substr($0, index($0, "=") + 1)}')"
  simple_at="$(printf '%s\n' "$audit" | awk -F= '/^simple_at=/{print substr($0, index($0, "=") + 1)}')"
  [ "$complex" = "0" ] || return 1
  # shellcheck disable=SC2086
  set -- $values
  [ "$#" -eq 1 ] && [ "$1" = "$want" ] || return 1
  # shellcheck disable=SC2086
  set -- $simple_at
  [ "$#" -eq 1 ] || return 1
  first_simple="$1"
  # shellcheck disable=SC2086
  set -- $barriers
  if [ "$#" -gt 0 ]; then
    first_barrier="$1"
    [ "$first_simple" -lt "$first_barrier" ] || return 1
  fi
  return 0
}

apply_runtime() {
  sysctl -w "vm.max_map_count=${want}"
  local now
  now="$(tr -d '[:space:]' < "$proc_file")"
  if [ "$now" != "$want" ]; then
    echo "The running vm.max_map_count is ${now}. It was not left at ${want}."
    return 1
  fi
  echo "Running vm.max_map_count=${now}."
}

restore_backup() {
  if [ ! -f "$backup_file" ] || [ -L "$backup_file" ]; then
    echo "The boot-file backup is missing, so the boot file was left as it is."
    return 1
  fi
  local mode tmp
  mode="$(stat -c '%a' "$backup_file")"
  tmp="$(mktemp "${go_file}.tmp.XXXXXX")"
  cp -p "$backup_file" "$tmp"
  mv -f "$tmp" "$go_file"
  chmod "$mode" "$go_file"
  cmp -s "$backup_file" "$go_file"
}

report_inspection() {
  local audit barriers
  if [ ! -e "$go_file" ]; then
    echo "Boot file ${go_file} was not found."
    return 0
  fi
  if [ -L "$go_file" ]; then
    echo "Boot file ${go_file} is a symlink. It was not read."
    return 0
  fi
  if ! audit="$(audit_go "$go_file")"; then
    echo "Boot file ${go_file} sets vm.max_map_count in a statement this script will not rewrite."
    return 0
  fi
  barriers="$(printf '%s\n' "$audit" | awk -F= '/^barriers=/{print substr($0, index($0, "=") + 1)}')"
  barriers="$(trim "$barriers")"
  if [ -n "$barriers" ]; then
    echo "Early exit or return on line ${barriers}."
    echo "A command appended after that statement would not run."
  else
    echo "No early exit or return would skip a command at the end of the boot file."
  fi
  if persistent_ok "$go_file"; then
    echo "The boot file already has one vm.max_map_count=${want} before any exit or return."
  fi
}

report_inspection

if [ "${MARKETING_MAP_COUNT_APPROVED:-0}" != "1" ]; then
  echo "Nothing was changed."
  exit 3
fi

if [ ! -e "$go_file" ]; then
  echo "Refusing: ${go_file} is missing. The kernel was not changed."
  exit 1
fi
if [ -L "$go_file" ] || [ ! -f "$go_file" ]; then
  echo "Refusing: ${go_file} is not a regular boot file. The kernel was not changed."
  exit 1
fi
if [ "$current" = "unreadable" ]; then
  echo "Refusing: ${proc_file} could not be read. The kernel was not changed."
  exit 1
fi

if ! audit_go "$go_file" >/dev/null; then
  echo "Refusing: ${go_file} sets vm.max_map_count in a statement this script will not rewrite."
  echo "The kernel was not changed."
  exit 1
fi

work="$(mktemp)"
original="$(mktemp)"
cleanup() {
  rm -f "$work" "$original"
}
trap cleanup EXIT
cp -p "$go_file" "$original"
rebuild_go "$go_file" "$work"

if cmp -s "$go_file" "$work"; then
  if ! persistent_ok "$go_file"; then
    echo "Refusing: ${go_file} does not keep vm.max_map_count=${want} before every exit or return."
    echo "The kernel was not changed."
    exit 1
  fi
  echo "Boot file already verified. No duplicate vm.max_map_count line was added."
else
  if [ -e "$backup_file" ]; then
    if [ -L "$backup_file" ] || [ ! -f "$backup_file" ]; then
      echo "Refusing: ${backup_file} is not a regular backup. The kernel was not changed."
      exit 1
    fi
    echo "Keeping the existing original backup ${backup_file}."
  else
    cp -p "$go_file" "$backup_file"
    chmod 600 "$meta_file" 2>/dev/null || true
    printf 'runtime=%s\n' "$current" > "$meta_file"
    chmod 600 "$meta_file"
    if ! cmp -s "$go_file" "$backup_file"; then
      echo "Refusing: the boot-file backup does not match the original. The kernel was not changed."
      rm -f "$backup_file" "$meta_file"
      exit 1
    fi
    echo "Backed up the original boot file to ${backup_file}."
  fi
  mode="$(stat -c '%a' "$go_file")"
  install_tmp="$(mktemp "${go_file}.tmp.XXXXXX")"
  cp "$work" "$install_tmp"
  mv -f "$install_tmp" "$go_file"
  chmod "$mode" "$go_file"
  if ! persistent_ok "$go_file"; then
    echo "The rewritten boot file failed verification. Restoring the backup."
    restore_backup || true
    echo "The kernel was not changed."
    exit 1
  fi
  echo "Verified ${go_file}: one vm.max_map_count=${want} runs before any exit or return."
fi

if ! apply_runtime; then
  if [ -f "$backup_file" ]; then
    echo "Restoring the original boot file because the running value could not be verified."
    restore_backup || true
  fi
  exit 1
fi
echo "Persistent boot file verified before the running kernel value was changed."
