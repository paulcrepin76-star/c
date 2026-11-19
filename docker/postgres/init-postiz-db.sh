#!/bin/sh
# Creates the Postiz role and the command/postiz databases on the existing
# resto Postgres. Safe to run more than once. Does not drop or rewrite data.
set -eu

until pg_isready -h postgres -U "$PGUSER" >/dev/null 2>&1; do
  sleep 1
done

psql -h postgres -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'postiz') THEN
    CREATE ROLE postiz LOGIN PASSWORD '${POSTIZ_DB_PASSWORD}';
  ELSE
    ALTER ROLE postiz WITH LOGIN PASSWORD '${POSTIZ_DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

if ! psql -h postgres -U "$PGUSER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='postiz'" | grep -q 1; then
  psql -h postgres -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE postiz OWNER postiz"
fi

if ! psql -h postgres -U "$PGUSER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='command'" | grep -q 1; then
  psql -h postgres -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE command"
fi

psql -h postgres -U "$PGUSER" -d postiz -v ON_ERROR_STOP=1 -c "GRANT ALL ON SCHEMA public TO postiz"
echo "postiz and command databases are ready"
