# Unraid setup

This stack is meant to live in `/mnt/user/appdata/resto` with invoice PDFs in `/mnt/user/documents/invoices-inbox`.

Unraid PUID/PGID is usually `99:100` (`nobody:users`). That is already in `.env.example`.

## Plugin

Install **Docker Compose Manager** (or Compose) from Community Applications. Point it at this folder. You can still install Paperless or Mealie from CA instead, but one shared Postgres is simpler to back up.

## First start

```bash
cp .env.example .env
nano .env   # passwords, tower IP, time zone
mkdir -p /mnt/user/documents/invoices-inbox
docker compose pull
docker compose up -d
docker compose ps
```

Give Paperless a minute on first boot (OCR stack + migrations). Then:

- resto-core: `http://TOWER:8088`
- Paperless: `http://TOWER:8010`
- Mealie: `http://TOWER:9925` — create the admin user, then set `ALLOW_SIGNUP=false` and recreate the container
- n8n: `http://TOWER:5678`
- Metabase: `http://TOWER:3001`

## Paperless mail

In Paperless: Settings → Mail → add the inbox that receives e-bills. Rules:

- FPL, water, Comcast, Waste Management → correspondent = supplier, type = utility
- Sam's Club / Chef's Warehouse → type = food
- Wine house → type = wine

The consume folder is enough when you download a PDF yourself. Share `invoices-inbox` over SMB if you want to drop files from a laptop.

## Metabase

During setup, Metabase uses its own `metabase` database.

Add another database connection:

- Engine: PostgreSQL
- Host: `postgres` (from another container) or `TOWER` port `5433`
- Database: `resto`
- User / password: the values in `.env`

Paste the queries in `metabase/questions.sql`. Pin food cost %, wine cost %, cellar value, and below-par wines on one dashboard.

## RAM

A small restaurant box is fine around 8–16 GB if you do not run a local LLM. Paperless OCR is the heavy piece. Pin Metabase and Mealie with the memory limits already in `compose.yml` if the array is tight.

## Backups

Back up `/mnt/user/appdata/resto` and the Paperless media folder with your usual Unraid backup (Appdata Backup / CA Backup). Postgres dump:

```bash
docker exec resto-postgres pg_dump -U resto resto > /mnt/user/backups/resto-$(date +%F).sql
```

## What not to do

- Do not expose Paperless, n8n, or Postgres to the internet without a reverse proxy and auth.
- Do not start with Playwright logins for FPL and Sam's Club. Get email ingest working first.
- Do not put live passwords in the Compose file or in this repo.
