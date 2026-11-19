# Survey Café marketing

This is the opt-in marketing layer. It does not replace n8n, resto-core, Paperless, or Mealie. `./scripts/remote-up.sh` does not start it. `./scripts/up-marketing.sh` does not load `compose.yml`, so it cannot create or recreate those services.

This workspace is not the Unraid host. A read-only SSH attempt to `100.116.48.120` timed out, so CPU, RAM, Docker network count, and ZFS recordsize were not measured on the server. Run `./scripts/preflight-marketing.sh` on Unraid before any start. The script only prints. It does not change sysctls, datasets, or containers.

## Pinned images

| Container | Image | Role | Host port |
| --- | --- | --- | --- |
| resto-mautic, cron, worker | `mautic/mautic:7.2.2-apache` | Mautic 7.2.2. One worker each for email, hits, and failures. PHP limit 512 MB | `BIND_ADDR:8084` |
| resto-mautic-mysql | `mysql:8.4.13` | Mautic 7 requires MySQL 8.4+ or MariaDB 10.11+. InnoDB buffer pool 256 MB. utf8mb4 | none |
| resto-postiz | `ghcr.io/gitroomhq/postiz-app:v2.26.0` | Social publisher. Not `:latest` | `BIND_ADDR:4007` |
| resto-postiz-postgres | `postgres:17.12-alpine` | Postiz tables and the dashboard database `command` | none |
| resto-postiz-redis | `redis:7.2.17` | Cache required by Postiz. Redis 6+ is the documented minimum | none |
| resto-temporal | `temporalio/auto-setup:1.28.1` | Required by Postiz since 2.12. `DB=postgres12` is the driver name Temporal uses for Postgres 12 and newer | none |
| resto-temporal-postgres | `postgres:16.16` | Temporal's own database. Official Postiz compose uses Postgres 16 | none |
| resto-temporal-elasticsearch | `elasticsearch:7.17.27` | Visibility store from the official Postiz compose. Heap 256 MB | none |
| resto-temporal-ui | `temporalio/ui:2.34.0` | Bound to `127.0.0.1:8085` only | localhost 8085 |
| resto-command | built from `apps/command` (`node:22.21.1-alpine`, `python:3.12.12-slim-bookworm`) | This dashboard | `BIND_ADDR:8090` |
| resto-marketing-db-init | `postgres:17.12-alpine` | Creates the `command` role on `postiz-postgres`, then exits | none |
| resto-marketing-edge | `caddy:2.10.2-alpine` | Optional public HTTPS. Not started by the marketing up script | 80 and 443, only after a separate approval |

Compatibility that was checked against current docs, not by booting the containers:

- Mautic 7.2.2 is the newest patch published on Docker Hub. The floating tag `7-apache` currently points at the same build. Mautic's site lists 7.2 as the active 7.x line and 7.2.2 (26 Oct 2026) as the latest security release. The 7.3 LTS date on their schedule has no Docker tag yet, so this file pins 7.2.2 instead of a floating major. PHP 8.2 through 8.5 and MySQL 8.4 or newer are the published requirements. MySQL 8.4.13 is past the Mautic 7.0.0 installer bug that rejected exactly 8.4.0.
- Mautic does not support PostgreSQL. Its MySQL is new and is not the resto database.
- Postiz documents PostgreSQL 14+, Redis 6+, and Temporal since v2.12. The official compose file uses Postgres 17, Redis 7.2, Temporal `1.28.1`, and Elasticsearch `7.17.27`. The pins above are those majors with current patch tags.
- Postiz and the dashboard do not use `resto-postgres`. If that container is stopped, the marketing stack leaves it stopped.

No memory cap is set. The MySQL buffer pool and the Elasticsearch heap are cache sizes, not kill switches.

`BIND_ADDR` defaults to `127.0.0.1` when it is unset. `.env.example` sets the Tailscale address `100.116.48.120`. `up-marketing.sh` refuses `0.0.0.0`.

## Memory and disk

Vendor guidance plus the pinned heap sizes. This is not a measurement from Unraid.

| Piece | Planning resident memory |
| --- | --- |
| MySQL 8.4, 256 MB buffer pool | 400–700 MB |
| Mautic web, cron, and one worker | 400 MB–1 GB idle, higher during a send |
| Postiz | 400–800 MB |
| Postiz Postgres 17 and Redis | about 150 MB together |
| Temporal Postgres 16 | 80–200 MB |
| Elasticsearch, 256 MB heap | 600–900 MB |
| Temporal and its UI | 300–550 MB |
| Dashboard | 80–150 MB |

Plan on about 3–5 GB once the stack is idle and about 6–8 GB while a campaign or a video upload is running. Preflight refuses to continue when `MemAvailable` is under 6 GiB unless you set `MARKETING_MEMORY_ACK=1` after reading the number. It also refuses when the one-minute load average is above twice the CPU count unless you set `MARKETING_LOAD_ACK=1`. Those switches do not raise a limit. They only record that you saw the warning.

Images want roughly 6 GB. Keep at least 20 GB free on the cache pool. New paths, all under `APPDATA` (Unraid: `/mnt/user/appdata/resto`):

- `mautic/` — MySQL and Mautic files
- `postiz/postgres`, `postiz/redis`, `postiz/config`, `postiz/uploads`
- `temporal/postgres`, `temporal/elasticsearch`
- `command/` — menu files and the dashboard data directory
- `caddy/` — only if you later approve the public edge

Backups do not go in those directories. See below.

## NVMe and ZFS

Preflight fails if `APPDATA` resolves under `/mnt/disk*`. On Unraid it reads `/boot/config/shares/appdata.cfg` and fails unless `shareUseCache="only"`. `shareUseCache="yes"` still lets the mover put files on the array. The script does not edit the share.

If `zfs` is installed, preflight prints `recordsize`, `compression`, `sync`, `logbias`, `primarycache`, and `atime` for the dataset mounted at the appdata path. Postgres and MySQL want `recordsize=16K`. A 128K dataset makes preflight fail until you set `MARKETING_ZFS_ACK=1` or create child datasets yourself. Example, with your real pool name:

```bash
zfs create -o recordsize=16K -o primarycache=metadata -o atime=off -o logbias=throughput cache/appdata/resto/mautic
zfs create -o recordsize=16K -o primarycache=metadata -o atime=off -o logbias=throughput cache/appdata/resto/postiz
zfs create -o recordsize=16K -o primarycache=metadata -o atime=off -o logbias=throughput cache/appdata/resto/temporal
```

Do that before the first start. Changing `recordsize` on a dataset that already holds a database does not rewrite the old blocks. These scripts never run `zfs create` or `zfs set`.

Elasticsearch still needs `vm.max_map_count=262144`. Preflight exits if the value is lower. It does not run `sysctl`. On Unraid:

```bash
sysctl -w vm.max_map_count=262144
```

Add the same line to `/boot/config/go`.

If the `resto` Docker network is missing and the daemon already has 30 or more networks, preflight stops. It does not prune networks. Creating one more network is a common way to hit "all predefined address pools have been fully subnetted." Clean unused networks yourself, then rerun preflight.

## What the scripts change

`./scripts/setup.sh`

- Does not start, stop, or remove containers. The old `docker rm` of `resto-paperless` and `resto-mealie` is gone.
- May create `/mnt/user/appdata/resto/{postgres,n8n,metabase,resto-core}` and the invoice inbox if they are missing.
- Fills empty marketing secrets in `.env`. It does not replace a password that is already set, and it does not print the values.
- Rewrites the Paperless, Mealie, and resto URL lines when those keys already exist.

`./scripts/preflight-marketing.sh`

- Reads memory, load, disk free space, `vm.max_map_count`, port binds, Docker network count, the appdata share setting, and ZFS properties.
- Exits non-zero when a check fails. Writes nothing. Starts nothing.

`./scripts/up-marketing.sh`

- With no approval, prints the plan and exits. `--dry-run` does the same and does not write `.env`.
- With `MARKETING_APPROVED=1`, runs preflight first. Only after preflight passes does it fill placeholder secrets, create the marketing directories, create the Docker network `resto` when it is absent, and start the marketing service list with `--no-recreate`.
- Records the container id and state of `resto-postgres`, `resto-n8n`, and the other protected names. If any of those change, the script exits 4.
- Does not run `docker rm`, `compose down`, or `compose up` against `compose.yml`.

`./scripts/up-public-edge.sh` starts only `resto-marketing-edge` after `MARKETING_PUBLIC_APPROVED=1`. It needs two DNS names and an ACME email. It does not publish the dashboard.

`./scripts/backup-marketing.sh` dumps Mautic MySQL, the Postiz database, the dashboard database, and Temporal. It refuses a destination inside `APPDATA`. Default on Unraid is `/mnt/user/backups/resto-marketing`. It does not dump `resto-postgres` and does not stop containers.

`./scripts/restore-marketing.sh` loads those dumps into the matching marketing containers only.

`./scripts/rollback-marketing.sh` removes only the marketing container names. Protected ids are compared before and after. Data directories stay unless `MARKETING_ROLLBACK_DELETE_DATA=1`, and that flag can delete only `mautic`, `postiz`, `temporal`, `command`, and `caddy` under `APPDATA`.

## Deploy

On the server, after you have read this and run preflight yourself:

```bash
cd /mnt/user/appdata/resto
git pull
./scripts/setup.sh
./scripts/preflight-marketing.sh
```

Fix anything preflight prints. Then:

```bash
MARKETING_APPROVED=1 ./scripts/up-marketing.sh
./scripts/measure-marketing.sh
```

Nothing in this repository starts that command. The approved run is the approval.

First visit, over Tailscale:

1. Open Mautic and create the admin user. Enable the API and create credentials.
2. Open Postiz, create the user, then connect networks there. Copy the public API key from Settings, Developers. OAuth providers cannot call a Tailscale address. Leave the accounts disconnected until the public edge below is in place, or connect only providers you can authorize from a host they can reach.
3. Set `POSTIZ_DISABLE_REGISTRATION=true` and run the up script again after the first user exists. `--no-recreate` keeps the running Postiz container, so registration stays at the value from the first start until you remove that marketing container yourself and run the up script again.
4. Open the dashboard. The password is `COMMAND_ADMIN_PASSWORD` in `.env`. Paste Mautic and Postiz credentials into Settings. They are encrypted with `COMMAND_SECRET_KEY`.
5. The session cookie is named `survey_command`, HttpOnly, SameSite lax, and lasts 12 hours. Set `COMMAND_HTTPS_ONLY=true` only when the dashboard itself is served over HTTPS. Tailscale HTTP must leave it false or the browser will drop the cookie.

n8n workflows in `n8n/marketing/` are imported by `./scripts/import-marketing-workflows.sh`. They stay inactive. The importer does not touch the Square, Mealie, or Paperless workflows. The n8n container definition is unchanged.

## Public HTTPS

Meta, TikTok, Google, and mail clients need a public hostname for OAuth callbacks, media fetch, and Mautic tracking links. The dashboard is not one of those endpoints.

When you have DNS and you want it:

```bash
# .env
PUBLIC_POSTIZ_HOST=social.example.com
PUBLIC_MAUTIC_HOST=mail.example.com
ACME_EMAIL=you@example.com
POSTIZ_URL=https://social.example.com
MARKETING_PUBLIC_APPROVED=1 ./scripts/up-public-edge.sh
```

Caddy is `caddy:2.10.2-alpine`. It proxies those two names to Postiz and Mautic on the Docker network. Mautic trusts proxies in `172.16.0.0/12` via `MAUTIC_TRUSTED_PROXIES`, which is where that Caddy container sits. After the certificate exists, set the Mautic site URL to `https://mail.example.com` inside Mautic. Set `POSTIZ_URL` to the public Postiz origin before connecting a social account, then recreate only the Postiz container when you are ready for it to pick up the new URL.

## Rollback

Before the first start, take the normal appdata backup. There is no marketing data yet, so a failed first start rolls back by removing the new containers:

```bash
MARKETING_ROLLBACK_APPROVED=1 ./scripts/rollback-marketing.sh
```

Add `MARKETING_ROLLBACK_DELETE_DATA=1` only when you also want the new directories removed. `resto-postgres` and `n8n` are not in that list.

After the stack has data:

```bash
MARKETING_BACKUP_APPROVED=1 ./scripts/backup-marketing.sh
```

Restore into containers that are already running:

```bash
MARKETING_RESTORE_APPROVED=1 ./scripts/restore-marketing.sh /mnt/user/backups/resto-marketing/STAMP
```

Uploaded images and Mautic media live in the appdata directories. The SQL dumps do not replace those files. Keep the Unraid appdata backup for them.

## Dashboard

React, TypeScript, and Tailwind, served by the FastAPI app. One owner session. Light and dark. The Connections page lists every integration with the proof we actually have. `live_verified` is false for all of them until a platform answers in production. Overview reachability is a local probe. It is not a completed post, email, or listing update.

A state of **confirmed** or **published** is stored only after the destination returns success.

## What each platform allows

Checked against the public docs. Self-hosted Postiz is the publisher for social posts. The clients below are implemented unless the Connections page says `not_implemented`. None of them have been called against the live services from this workspace.

| Platform | Listings | Reviews | Posts or ads | Proof so far |
| --- | --- | --- | --- | --- |
| Google Business Profile | Supported for a manager of the location, OAuth scope `business.manage` | Read and reply supported | Local posts go through Postiz | Unit test with a stubbed HTTP client. No live Google call |
| Apple Business Connect | Needs Apple API approval | Not in that API | Showcases need the same approval | No client |
| Yelp Fusion | No write API | Up to three excerpts, read only | Replies are typed on Yelp | Unit test: push stays manual, reply stays unavailable. The excerpt client has not been called |
| Tripadvisor | No public owner write API | Partner read API only | Management Center | No client |
| Facebook | Not a listing API | Page reviews need Meta app review | Posts through Postiz once the Page is connected | Unit test stops before a network call when the Postiz key is missing |
| Instagram | None | None | Professional account plus media, through Postiz | Unit test refuses a text-only post before any network call |
| TikTok | None | None | Video only, and TikTok must approve the app | Rules exist. No TikTok request has been made |
| Google Ads | None | None | Read spend after Google approves a developer token. Test tokens see test accounts | Client exists. No token and no live call |
| Meta Ads | None | None | `ads_read`. Development apps can read accounts owned by their admins | Client exists. No token and no live call |
| Mautic | Local | None | Campaigns are created unpublished | Client exists. No Mautic call from the tests |
| Postiz | Local | None | Publisher | Unit test. No Postiz server was contacted |
| n8n | Local | None | Inactive workflow files | Dashboard endpoint tested with the API key. Workflows were not imported |

Google Ads and Meta calls use API versions `v18` and `v21.0` until you change `GOOGLE_ADS_API_VERSION` or `META_GRAPH_VERSION`. If a version is retired, the sync shows the error and does not invent numbers.

## AI

If `OLLAMA_BASE_URL` and `OLLAMA_TEXT_MODEL` are set, review replies and event captions are drafted by that model and labeled `ollama`. If `OLLAMA_VISION_MODEL` is set, menu photos are sent to it and only priced lines are kept. With no model, the dashboard writes a fill-in draft and labels it `template`. Menu text and text-based PDFs are parsed locally without a model. No Ollama server was called from the tests.
