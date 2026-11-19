#!/bin/sh
# Creates the dashboard role and database on the marketing Postgres (postiz-postgres).
# Safe to run more than once. Does not connect to resto-postgres and does not drop data.
set -eu

until pg_isready -h postiz-postgres -U postiz -d postiz >/dev/null 2>&1; do
  sleep 1
done

psql -h postiz-postgres -U postiz -d postiz -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'command') THEN
    CREATE ROLE command LOGIN PASSWORD '${COMMAND_DB_PASSWORD}';
  ELSE
    ALTER ROLE command WITH LOGIN PASSWORD '${COMMAND_DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

if ! psql -h postiz-postgres -U postiz -d postiz -tAc "SELECT 1 FROM pg_database WHERE datname='command'" | grep -q 1; then
  psql -h postiz-postgres -U postiz -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE command OWNER command"
fi

echo "command database is ready on postiz-postgres. resto-postgres was not contacted."
