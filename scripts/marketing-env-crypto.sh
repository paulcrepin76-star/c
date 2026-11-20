# Encrypt and decrypt the marketing .env.
# The passphrase is MARKETING_ENV_PASSPHRASE. It stays in the environment.
# These functions do not print it and do not write it to disk.
# shellcheck shell=bash

marketing_env_passphrase_ok() {
  if [ -z "${MARKETING_ENV_PASSPHRASE:-}" ]; then
    echo "Set MARKETING_ENV_PASSPHRASE in the environment. It is not written to disk and it is not printed."
    exit 1
  fi
  if [ "${#MARKETING_ENV_PASSPHRASE}" -lt 16 ]; then
    echo "MARKETING_ENV_PASSPHRASE must be at least 16 characters. Nothing was written."
    exit 1
  fi
}

marketing_env_encrypt() {
  local input="$1"
  local output="$2"
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
    -in "$input" -out "$output" \
    -pass env:MARKETING_ENV_PASSPHRASE
}

marketing_env_decrypt() {
  local input="$1"
  local output="$2"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -salt \
    -in "$input" -out "$output" \
    -pass env:MARKETING_ENV_PASSPHRASE
}

marketing_env_wipe() {
  local file="$1"
  local size
  [ -f "$file" ] || return 0
  size="$(wc -c < "$file" | tr -d ' ')"
  if [ "${size:-0}" -gt 0 ]; then
    dd if=/dev/zero of="$file" bs="$size" count=1 conv=notrunc status=none 2>/dev/null || true
  fi
  rm -f "$file"
}
