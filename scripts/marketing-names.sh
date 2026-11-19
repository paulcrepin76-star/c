# Container names the marketing scripts are allowed to create, stop, or remove.
# shellcheck shell=bash
MARKETING_CONTAINERS=(
  resto-mautic
  resto-mautic-cron
  resto-mautic-worker
  resto-mautic-mysql
  resto-postiz
  resto-postiz-postgres
  resto-postiz-redis
  resto-marketing-db-init
  resto-temporal
  resto-temporal-postgres
  resto-temporal-elasticsearch
  resto-temporal-ui
  resto-command
  resto-marketing-edge
)

# Existing production containers. Marketing scripts may inspect these ids and must not
# start, stop, remove, or recreate them.
PROTECTED_CONTAINERS=(
  resto-postgres
  resto-n8n
  resto-core
  resto-metabase
  resto-redis
  resto-paperless
  resto-mealie
  resto-homeassistant
  resto-frigate
  resto-price-collector
  resto-mosquitto
  resto-gotenberg
  resto-tika
)

# Directories under APPDATA that belong to the marketing stack.
# Rollback may delete these only when MARKETING_ROLLBACK_DELETE_DATA=1.
MARKETING_DATA_DIRS=(
  mautic
  postiz
  temporal
  command
  caddy
)
