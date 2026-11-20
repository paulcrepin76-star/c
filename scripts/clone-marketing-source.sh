#!/usr/bin/env bash
# Clones a detached marketing checkout on the NVMe pool.
# Does not run git commands in /mnt/cache/appdata/resto or /mnt/user/appdata/resto.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/marketing-guard.sh"

export GIT_OPTIONAL_LOCKS=0

dest="${MARKETING_SOURCE:-/mnt/cache/projects/resto-marketing}"
remote="${MARKETING_REMOTE:-https://github.com/paulcrepin76-star/c.git}"
branch="${MARKETING_BRANCH:-cursor/marketing-deploy-safety-7375}"
# 95aa65b is the subnet inspection. cc57ca5 is the stacked marketing pull request.
# d82e03f is the quoted-env commit. e8f9184 is the reviewed installer commit.
ancestor_subnet="95aa65bc110b6baa8aec840d5f824f684b8f4d5f"
ancestor_stack="cc57ca5d18222ef51114f6937a60bc9ac6c163f1"
ancestor_approved="d82e03f39aaa74d34c59ea009d7a4b8fb15a170a"
ancestor_installer="e8f918406dd0b004e5d1c4ee64d4654ba4e03939"

marketing_refuse_production "$dest"

if [ "${MARKETING_CLONE_APPROVED:-0}" != "1" ]; then
  echo "Nothing was cloned."
  echo "When you approve it, this creates ${dest} and detaches HEAD at MARKETING_DEPLOY_COMMIT."
  echo "A branch tip is not checked out."
  echo "The production tree /mnt/cache/appdata/resto is not read or written by git."
  exit 3
fi

deploy_commit="$(printf '%s' "${MARKETING_DEPLOY_COMMIT:-}" | tr '[:upper:]' '[:lower:]')"
if ! printf '%s\n' "$deploy_commit" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "Refusing: MARKETING_DEPLOY_COMMIT must be the full 40-character SHA. A branch tip is not checked out. Nothing was cloned."
  exit 1
fi

if [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null || true)" ]; then
  echo "Refusing: ${dest} already exists. Nothing was cloned."
  exit 1
fi

mkdir -p "$(dirname "$dest")"
git clone --origin origin "$remote" "$dest"
git -C "$dest" fetch origin "$branch"
git -C "$dest" checkout --detach "$deploy_commit"
head_commit="$(git -C "$dest" rev-parse HEAD)"
if [ "$head_commit" != "$deploy_commit" ]; then
  echo "Refusing: HEAD is ${head_commit}, not ${deploy_commit}."
  exit 1
fi

if ! git -C "$dest" merge-base --is-ancestor "$ancestor_subnet" HEAD; then
  echo "Refusing: ${dest} does not contain ${ancestor_subnet}."
  exit 1
fi
if ! git -C "$dest" merge-base --is-ancestor "$ancestor_stack" HEAD; then
  echo "Refusing: ${dest} does not contain the stacked marketing commit ${ancestor_stack}."
  exit 1
fi
if ! git -C "$dest" merge-base --is-ancestor "$ancestor_approved" HEAD; then
  echo "Refusing: ${dest} does not contain the approved Mautic commit ${ancestor_approved}."
  exit 1
fi
if ! git -C "$dest" merge-base --is-ancestor "$ancestor_installer" HEAD; then
  echo "Refusing: ${dest} does not contain the reviewed installer commit ${ancestor_installer}."
  exit 1
fi

echo "Marketing source: ${dest}"
echo "HEAD ${head_commit}"
echo "This checkout is exactly ${deploy_commit}."
echo "This checkout contains ${ancestor_subnet}, ${ancestor_stack}, ${ancestor_approved}, and ${ancestor_installer}."
echo "The production tree was not checked out, reset, cleaned, or pulled."
