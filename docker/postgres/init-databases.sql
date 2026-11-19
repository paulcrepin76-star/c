CREATE DATABASE paperless;
CREATE DATABASE mealie;
CREATE DATABASE n8n;
CREATE DATABASE metabase;
-- Dashboard tables only. Postiz gets its own role from docker/postgres/init-postiz-db.sh
-- because this file runs before that role exists. Existing volumes do not re-run this file.
CREATE DATABASE command;
