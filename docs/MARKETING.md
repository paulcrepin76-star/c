# Survey Café marketing

This is the opt-in marketing layer for the existing Unraid stack. It does not replace n8n, resto-core, Paperless, or Mealie, and a normal `./scripts/remote-up.sh` does not start it.

## What is already here

One Compose project named `resto`, on the Docker network `resto`, with data under `/mnt/user/appdata/resto` on the NVMe-backed Unraid appdata share.

| Container | Host port | Job |
| --- | --- | --- |
| resto-core | 8088 | Wine, invoices, costing |
| n8n | 5678 | Nightly sync. Secrets stay out of the workflows |
| postgres | 5433 | Databases `resto`, `n8n`, `metabase`, and, when created, `paperless` and `mealie` |
| metabase | 3001 | Costing charts |
| price-collector | 8099 / 7900 | Supplier login browser |
| homeassistant | 8123 | Fridge sensors |
| frigate | 8971 | Cameras |

Paperless and Mealie already run on the server and are not part of the default start. Redis in this compose file is behind the `paperless` profile, so Postiz does not borrow it.

This cloud workspace is not the Unraid host. It has no Docker daemon, so the containers were not started here and RAM after install was not measured on the server. `scripts/measure-marketing.sh` records that on Unraid.

## What gets added

`compose.marketing.yml` is merged only by `scripts/up-marketing.sh`.

| New container | Why it exists | Host port |
| --- | --- | --- |
| resto-mautic, cron, worker | Official `mautic/mautic:5-apache`. Cron and one worker each for email, hits, and failures | 8084 |
| resto-mautic-mysql | Mautic 5 supports MySQL 8, not Postgres. MySQL 8.4, InnoDB buffer pool 256 MB | none |
| resto-postiz | Official `ghcr.io/gitroomhq/postiz-app:latest` | 4007 |
| resto-postiz-redis | Postiz requires Redis. The Paperless Redis is not always running | none |
| resto-temporal + UI | Postiz has required Temporal since 2.12. UI is bound to 127.0.0.1:8085 | 8085 on localhost |
| resto-temporal-postgres | Temporal's own Postgres 16, so its setup user is not the resto superuser | none |
| resto-temporal-elasticsearch | The visibility store shipped in the official Postiz compose. Heap 256 MB | none |
| resto-command | This dashboard | 8090 |
| resto-marketing-db-init | Creates the `postiz` role and the `command` database, then exits | none |

Postiz application tables go in database `postiz` on the existing `resto-postgres`. That avoids a third Postgres server. The official Postiz compose ships its own Postgres 17; Postgres 16 is inside the range Postiz documents (14+).

No memory cap is set on these containers. A cap that is too small kills a campaign send. The MySQL buffer pool and the Elasticsearch heap are cache sizes, not kill switches.

## Memory and disk

Vendor guidance, not a measurement from the Unraid box:

- Postiz documents 2 GB for a light all-in-one install and 8 GB when Postgres, Redis, and Temporal are busy.
- Mautic's own PHP limit in the official image is 512 MB per process. This file keeps that and runs one consumer per queue instead of the image default of two.
- Elasticsearch is the extra cost of the official Temporal file. Plan on roughly 0.5–1 GB for it even with a 256 MB heap.

A reasonable planning range once everything is idle is about 4 GB resident, and about 6–8 GB while a campaign or a video upload is in flight. The server has about 82 GB, so the headroom is there. Confirm it with:

```bash
./scripts/measure-marketing.sh
MARKETING_APPROVED=1 ./scripts/up-marketing.sh
./scripts/measure-marketing.sh
```

Images plus databases want on the order of 8 GB, and uploads will grow. Keep at least 20 GB free on the appdata share. Paths:

- `/mnt/user/appdata/resto/mautic` — MySQL and Mautic files
- `/mnt/user/appdata/resto/postiz` — uploads, config, Redis
- `/mnt/user/appdata/resto/temporal` — Temporal Postgres and Elasticsearch
- `/mnt/user/appdata/resto/command` — menu files
- `/mnt/user/appdata/resto/postgres` — existing Postgres, plus the new `postiz` and `command` databases

Backups stay your existing appdata backup plus `pg_dump`. The dashboard export downloads its own records and omits secrets.

## Install

On the server, after you have read this:

```bash
cd /mnt/user/appdata/resto
git pull
./scripts/setup.sh
./scripts/preflight-marketing.sh
```

Preflight refuses to continue when `vm.max_map_count` is below 262144. Elasticsearch needs that. The script does not change the kernel. On Unraid:

```bash
sysctl -w vm.max_map_count=262144
```

Add the same line to `/boot/config/go` so it survives reboot.

Then:

```bash
MARKETING_APPROVED=1 ./scripts/up-marketing.sh
```

The script writes missing passwords into `.env` without printing them, starts only the marketing services, and checks that `resto-n8n`, `resto-postgres`, and the other current containers kept the same container id.

First visit:

1. Open Mautic at `http://100.116.48.120:8084` and create the admin user. In Mautic, enable the API and create credentials.
2. Open Postiz at `http://100.116.48.120:4007`, create the user, connect Facebook, Instagram, TikTok, and Google Business there, then copy the public API key from Settings → Developers.
3. Set `POSTIZ_URL` to the Tailscale URL browsers actually use. Postiz OAuth redirects depend on it. Then set `POSTIZ_DISABLE_REGISTRATION=true` and run the up script again.
4. Open the dashboard at `http://100.116.48.120:8090`. The password is `COMMAND_ADMIN_PASSWORD` in `.env`.
5. Paste the Mautic and Postiz credentials into Settings. They are encrypted with `COMMAND_SECRET_KEY`.

Meta and TikTok app ids, when you have them, go in `.env` as `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `TIKTOK_CLIENT_ID`, and `TIKTOK_CLIENT_SECRET`. They are not committed.

n8n workflows in `n8n/marketing/` are imported by `./scripts/import-marketing-workflows.sh`. They stay inactive. The importer does not touch the Square, Mealie, or Paperless workflows, and the n8n container definition is unchanged. The workflows call the dashboard with the existing `RESTO_API_KEY`.

## Dashboard

React, TypeScript, and Tailwind, served by a small FastAPI app so the stack stays on the same Python and Postgres you already run. One owner session. Light and dark. The pages read and write the `command` database and, when credentials exist, the Mautic and Postiz APIs.

A state of **confirmed** or **published** is stored only after the destination returns success. A draft, a manual listing, and a refused call stay labeled as such.

## What each platform allows

Checked against the public docs for this install. Self-hosted Postiz is the publisher for social posts.

| Platform | Listings | Reviews | Posts or ads |
| --- | --- | --- | --- |
| Google Business Profile | Supported for a manager of the location, OAuth scope `business.manage` | Read and reply supported | Local posts go through Postiz |
| Apple Business Connect | Needs Apple API approval | Not in that API | Showcases need the same approval |
| Yelp Fusion | No write API | Up to three excerpts, read only | Replies are typed on Yelp |
| Tripadvisor | No public owner write API | Partner read API only | Management Center |
| Facebook | Not a listing API | Page reviews need Meta app review | Posts through Postiz once the Page is connected. `pages_manage_posts` needs App Review beyond the app admins |
| Instagram | None | None | Professional account plus media, through Postiz |
| TikTok | None | None | Video only, and TikTok must approve the app |
| Google Ads | None | None | Read spend after Google approves a developer token. Test tokens see test accounts |
| Meta Ads | None | None | `ads_read`. Development apps can read accounts owned by their admins |

Google Ads and Meta calls use API versions `v18` and `v21.0` until you change `GOOGLE_ADS_API_VERSION` or `META_GRAPH_VERSION`. If a version is retired, the sync shows the error and does not invent numbers.

## AI

If `OLLAMA_BASE_URL` and `OLLAMA_TEXT_MODEL` are set, review replies and event captions are drafted by that model and labeled `ollama`. If `OLLAMA_VISION_MODEL` is set, menu photos are sent to it and only priced lines are kept. With no model, the dashboard writes a fill-in draft and labels it `template`. Menu text and text-based PDFs are parsed locally without a model.
