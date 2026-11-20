# Refuses the production resto tree and keeps marketing source and data apart.
# shellcheck shell=bash

marketing_resolve() {
  readlink -f "$1" 2>/dev/null || printf '%s\n' "$1"
}

marketing_refuse_production() {
  local path resolved item
  path="$1"
  resolved="$(marketing_resolve "$path")"
  for item in /mnt/cache/appdata/resto /mnt/user/appdata/resto; do
    case "$resolved" in
      "$item"|"$item"/*)
        echo "Refusing: ${path} is inside the production resto tree ${item}."
        echo "Marketing source belongs at /mnt/cache/projects/resto-marketing."
        echo "Marketing data belongs at /mnt/cache/appdata/surveycafe-marketing."
        echo "Nothing was changed."
        exit 1
        ;;
    esac
  done
}

marketing_require_separate_paths() {
  local root="$1"
  local appdata="$2"
  local resolved_root resolved_data want_root want_data
  marketing_refuse_production "$root"
  marketing_refuse_production "$appdata"
  resolved_root="$(marketing_resolve "$root")"
  resolved_data="$(marketing_resolve "$appdata")"
  if [ "$resolved_root" = "$resolved_data" ]; then
    echo "Refusing: source and APPDATA are the same directory (${resolved_root})."
    echo "Nothing was changed."
    exit 1
  fi
  case "$resolved_data" in
    "$resolved_root"/*)
      echo "Refusing: APPDATA ${resolved_data} is inside the source checkout."
      echo "Nothing was changed."
      exit 1
      ;;
  esac
  if [ -d /mnt/cache/appdata/resto ]; then
    want_root="$(marketing_resolve "${MARKETING_SOURCE:-/mnt/cache/projects/resto-marketing}")"
    want_data="$(marketing_resolve "${MARKETING_APPDATA:-/mnt/cache/appdata/surveycafe-marketing}")"
    if [ "$resolved_root" != "$want_root" ]; then
      echo "Refusing: this checkout is ${resolved_root}. Marketing source must be ${want_root}."
      echo "Nothing was changed."
      exit 1
    fi
    if [ "$resolved_data" != "$want_data" ]; then
      echo "Refusing: APPDATA is ${resolved_data}. Marketing data must be ${want_data}."
      echo "Nothing was changed."
      exit 1
    fi
  fi
}

marketing_is_owned() {
  local name="$1" item
  for item in "${MARKETING_CONTAINERS[@]}"; do
    if [ "$item" = "$name" ]; then
      return 0
    fi
  done
  return 1
}

# Every container that marketing does not own. New marketing names are omitted
# so their first start does not look like an existing container changed.
marketing_snapshot_others() {
  local names name
  names="$(docker ps -a --format '{{.Names}}' | LC_ALL=C sort)"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if marketing_is_owned "$name"; then
      continue
    fi
    docker inspect -f '{{.Name}} {{.Id}} {{.State.Status}}' "$name"
  done <<< "$names"
}
