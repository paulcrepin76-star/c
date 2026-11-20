#!/usr/bin/env bash
# Restores an encrypted marketing .env into the marketing checkout only.
# Does not print secrets, start containers, or touch the production resto tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env.sh"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-env-crypto.sh"
marketing_refuse_production "$ROOT"

src="${1:-}"
if [ "${MARKETING_ENV_RESTORE_APPROVED:-0}" != "1" ]; then
  echo "Nothing was restored."
  echo "Pass the directory created by backup-marketing-env.sh:"
  echo "  MARKETING_ENV_PASSPHRASE='...' MARKETING_ENV_RESTORE_APPROVED=1 ./scripts/restore-marketing-env.sh /mnt/user/backups/resto-marketing/env/STAMP"
  echo "An existing checkout .env is left in place unless MARKETING_ENV_RESTORE_OVERWRITE=1."
  exit 3
fi

marketing_env_passphrase_ok

if [ -z "$src" ]; then
  echo "Backup directory not found. Nothing was restored."
  exit 1
fi
if [ -d "$src" ]; then
  cipher="${src}/marketing.env.enc"
else
  cipher="$src"
  src="$(dirname "$cipher")"
fi
if [ ! -f "$cipher" ]; then
  echo "Encrypted marketing .env not found. Nothing was restored."
  exit 1
fi

marketing_refuse_production "$cipher"
dest_file="${MARKETING_ENV_FILE:-$ROOT/.env}"
marketing_refuse_production "$dest_file"
if [ -L "$dest_file" ]; then
  echo "Refusing: ${dest_file} is a symlink. Nothing was restored."
  exit 1
fi

if [ -e "$dest_file" ] && [ "${MARKETING_ENV_RESTORE_OVERWRITE:-0}" != "1" ]; then
  echo "Refusing to overwrite ${dest_file}. Set MARKETING_ENV_RESTORE_OVERWRITE=1 to replace it. Nothing was written."
  exit 1
fi

if [ -f "${src}/marketing.env.enc.sha256" ]; then
  actual="$(sha256sum "$cipher" | awk '{print $1}')"
  expected="$(awk 'NF {print $1; exit}' "${src}/marketing.env.enc.sha256")"
  if [ "$actual" != "$expected" ]; then
    echo "Ciphertext checksum does not match. Nothing was restored."
    exit 1
  fi
fi

umask 077
check="$(mktemp)"
chmod 600 "$check"
cleanup() {
  marketing_env_wipe "$check"
}
trap cleanup EXIT

if ! marketing_env_decrypt "$cipher" "$check"; then
  echo "Could not decrypt the marketing .env. The passphrase was not correct, or the file is damaged. Nothing was restored."
  exit 1
fi
if ! env -i PATH="$PATH" bash --noprofile --norc -c '
set -euo pipefail
set -a
source "$1"
set +a
test -n "${MAUTIC_DB_PASSWORD:-}"
test -n "${MAUTIC_DB_ROOT_PASSWORD:-}"
test -n "${COMMAND_SECRET_KEY:-}"
' bash "$check"; then
  echo "The decrypted file cannot be sourced, or a required key is missing. Nothing was restored."
  exit 1
fi

appdata="$(marketing_env_value "$check" APPDATA)"
if [ -n "$appdata" ]; then
  marketing_refuse_production "$appdata"
  resolved_dest="$(marketing_resolve "$dest_file")"
  resolved_data="$(marketing_resolve "$appdata")"
  case "$resolved_dest" in
    "$resolved_data"|"$resolved_data"/*)
      echo "Refusing to write the marketing .env inside APPDATA. Nothing was restored."
      exit 1
      ;;
  esac
fi

install -m 600 "$check" "$dest_file"
echo "Restored marketing .env to ${dest_file}. Mode 600. Values were not printed."
