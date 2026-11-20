#!/usr/bin/env bash
# Encrypts the marketing .env and writes the ciphertext outside the source checkout and outside APPDATA.
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

ENV_FILE="${MARKETING_ENV_FILE:-$ROOT/.env}"
marketing_refuse_production "$ENV_FILE"

if [ "${MARKETING_ENV_BACKUP_APPROVED:-0}" != "1" ]; then
  echo "Nothing was copied."
  echo "The marketing .env lives in the source checkout, outside appdata. It holds database passwords and encryption keys."
  echo "Database dumps do not include it. This script encrypts that file with AES-256-CBC and PBKDF2."
  echo "The ciphertext is stored outside the source checkout and outside APPDATA. The passphrase is not written."
  echo "  MARKETING_ENV_PASSPHRASE='...' MARKETING_ENV_BACKUP_APPROVED=1 ./scripts/backup-marketing-env.sh"
  exit 3
fi

marketing_env_passphrase_ok

if [ ! -f "$ENV_FILE" ]; then
  echo "No marketing .env at ${ENV_FILE}. Nothing was copied."
  exit 1
fi

if [ -L "$ENV_FILE" ]; then
  echo "Refusing: ${ENV_FILE} is a symlink. Nothing was copied."
  exit 1
fi

appdata="$(marketing_env_value "$ENV_FILE" APPDATA)"
if [ -z "$appdata" ]; then
  appdata="${APPDATA:-}"
fi
if [ -n "$appdata" ]; then
  marketing_refuse_production "$appdata"
fi

if [ -z "${MARKETING_ENV_BACKUP_DIR:-}" ]; then
  if [ -d /mnt/user/backups ]; then
    MARKETING_ENV_BACKUP_DIR=/mnt/user/backups/resto-marketing/env
  else
    echo "Set MARKETING_ENV_BACKUP_DIR to a path outside the source checkout and outside APPDATA. Nothing was copied."
    exit 1
  fi
fi

marketing_refuse_production "$MARKETING_ENV_BACKUP_DIR"

refuse_inside() {
  local dest="$1"
  local parent="$2"
  local label="$3"
  local resolved_dest resolved_parent
  [ -n "$parent" ] || return 0
  resolved_dest="$(marketing_resolve "$dest")"
  resolved_parent="$(marketing_resolve "$parent")"
  case "$resolved_dest" in
    "$resolved_parent"|"$resolved_parent"/*)
      echo "Refusing to store the marketing .env backup inside ${label} (${resolved_parent})."
      echo "Nothing was copied."
      exit 1
      ;;
  esac
}

refuse_inside "$MARKETING_ENV_BACKUP_DIR" "$ROOT" "the source checkout"
refuse_inside "$MARKETING_ENV_BACKUP_DIR" "$appdata" "APPDATA"

umask 077
if ! chmod 600 "$ENV_FILE"; then
  echo "Could not set ${ENV_FILE} to mode 600. Nothing was copied."
  exit 1
fi

if [ -n "${MARKETING_ENV_BACKUP_STAMP:-}" ]; then
  case "$MARKETING_ENV_BACKUP_STAMP" in
    *[!A-Za-z0-9._-]*)
      echo "Refusing backup stamp. Nothing was copied."
      exit 1
      ;;
  esac
  stamp="$MARKETING_ENV_BACKUP_STAMP"
else
  stamp="$(date +%F-%H%M%S)"
fi
dest="${MARKETING_ENV_BACKUP_DIR}/${stamp}"
cipher_tmp="$(mktemp)"
check="$(mktemp)"
chmod 600 "$cipher_tmp" "$check"
cleanup() {
  if [ -n "${check:-}" ]; then
    marketing_env_wipe "$check"
  fi
  if [ -n "${cipher_tmp:-}" ]; then
    rm -f "$cipher_tmp"
  fi
}
trap cleanup EXIT

if ! marketing_env_encrypt "$ENV_FILE" "$cipher_tmp"; then
  echo "Encryption failed. Nothing was copied."
  exit 1
fi
if ! marketing_env_decrypt "$cipher_tmp" "$check"; then
  echo "The encrypted copy could not be decrypted. Nothing was copied."
  exit 1
fi
if ! cmp -s "$ENV_FILE" "$check"; then
  echo "The encrypted copy did not decrypt to the original file. Nothing was copied."
  exit 1
fi
env -i PATH="$PATH" bash --noprofile --norc -c '
set -euo pipefail
set -a
source "$1"
set +a
test -n "${MAUTIC_DB_PASSWORD:-}"
test -n "${MAUTIC_DB_ROOT_PASSWORD:-}"
test -n "${COMMAND_SECRET_KEY:-}"
' bash "$check"

mkdir -p "$dest"
chmod 700 "$MARKETING_ENV_BACKUP_DIR" "$dest"
mv "$cipher_tmp" "$dest/marketing.env.enc"
cipher_tmp=""
chmod 600 "$dest/marketing.env.enc"
sha256sum "$dest/marketing.env.enc" | awk '{print $1}' > "$dest/marketing.env.enc.sha256"
chmod 600 "$dest/marketing.env.enc.sha256"
cat > "$dest/README.txt" <<EOF
Marketing .env backup ${stamp}
This directory holds an encrypted copy of the marketing checkout .env.
It is outside the source checkout and outside APPDATA.
Database dumps do not include this file.
Cipher: AES-256-CBC, PBKDF2, 600000 iterations, salted.
The passphrase was not written here. Plaintext values were not written here.
Restore with:
  MARKETING_ENV_PASSPHRASE='...' MARKETING_ENV_RESTORE_APPROVED=1 ./scripts/restore-marketing-env.sh ${dest}
EOF
chmod 600 "$dest/README.txt"
echo "Encrypted marketing .env: ${dest}/marketing.env.enc"
echo "Passphrase was not written. Mode 600. Database dumps do not include this file."
