#!/usr/bin/env bash
# Build Survey Cafe questions and dashboard in Metabase. Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

docker exec resto-core python -c "from app.db import SessionLocal; from app.intel import snapshot_recipe_costs; db=SessionLocal(); n=snapshot_recipe_costs(db); db.close(); print('recipe snapshots', n)"

docker run --rm --network resto \
  -v "$ROOT:/work" \
  -e MB_URL=http://metabase:3000 \
  -e POSTGRES_USER \
  -e POSTGRES_PASSWORD \
  -e POSTGRES_DB \
  -e METABASE_PUBLIC_URL="${METABASE_URL:-http://100.116.48.120:3001}" \
  python:3.12-slim \
  bash -c "pip install -q bcrypt httpx psycopg2-binary && python /work/scripts/setup_metabase.py"
