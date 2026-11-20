# Survey Café marketing

This is the opt-in marketing layer. It does not replace n8n, resto-core, Paperless, or Mealie. `./scripts/remote-up.sh` does not start it. `./scripts/up-marketing.sh` does not load `compose.yml`, so it cannot create or recreate those services.

The production checkout on Unraid is `/mnt/cache/appdata/resto`. Marketing does not run git there. Source code is checked out at `/mnt/cache/projects/resto-marketing`, and container data is `/mnt/cache/appdata/surveycafe-marketing`.

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

Images want roughly 6 GB. The Docker image has about 98 GB free, and the NVMe pool has about 3.2 TB free. Marketing data lives under `APPDATA` (`/mnt/cache/appdata/surveycafe-marketing`), not in the production tree:

- `mautic/` — MySQL and Mautic files
- `postiz/postgres`, `postiz/redis`, `postiz/config`, `postiz/uploads`
- `temporal/postgres`, `temporal/elasticsearch`
- `command/` — menu files and the dashboard data directory
- `caddy/` — only if you later approve the public edge

Backups do not go in those directories. See below.

## NVMe and ZFS

Preflight is read-only. It does not edit the share, the pool, or any dataset, and it does not run `zfs create`, `zfs set`, or `sysctl`.

On Unraid 7 it reads `/boot/config/shares/appdata.cfg`. Primary storage is `shareCachePool`. Secondary storage is `shareCachePool2` when that is set, otherwise the array when `shareUseCache` is `yes` or `prefer`, and None when `shareUseCache` is `only`. Marketing data is accepted only when all of these are true:

- `APPDATA` is under `/mnt/user/appdata` or a pool's `appdata` directory.
- Primary storage is a named pool, not the array.
- Secondary storage is None. A secondary array lets the mover put MySQL and Postgres on HDDs. A second pool is also refused.
- The primary pool's disks report NVMe (`zpool status`, `findmnt`, or `/sys/block/*/queue/rotational`).
- No existing `mautic`, `postiz`, `temporal`, `command`, or `caddy` path is already on `/mnt/diskN`.

A path under `/mnt/diskN` is a hard failure. There is no acknowledgment flag that bypasses it.

ZFS record size is reported per directory and never blocks the preflight. A shared 128K parent is acceptable for a first install. Child datasets are optional and are not created by these scripts.

| Path | Workload | Record size that fits |
| --- | --- | --- |
| `mautic/mysql` | MySQL InnoDB, 16K pages | 16K |
| `postiz/postgres` | Postgres, 8K pages | 16K |
| `temporal/postgres` | Postgres, 8K pages | 16K |
| `temporal/elasticsearch` | Lucene segments | 128K |
| `postiz/uploads`, `mautic/media` | Sequential media | 1M |
| Redis, config, logs, command files | Small or mixed files | 16K to 128K, pool default is fine |

Elasticsearch, started by the Postiz stage, needs `vm.max_map_count=262144`. The Mautic stage does not. Preflight prints the current value and exits before Postiz when it is lower. It does not change the kernel. On Unraid, after you decide to allow it:

```bash
sysctl -w vm.max_map_count=262144
```

Add the same line to `/boot/config/go`.

Marketing joins the existing Docker network named `resto`. Preflight reads every network subnet, the addresses already attached, and the host routes that are not Docker bridges. It refuses when `resto` overlaps another Docker subnet, when that subnet overlaps a host route, or when fewer than 16 IPv4 addresses are free on it. If `resto` is missing, preflight looks for one free subnet in the daemon address pools, or in Docker's built-in local pools when the daemon has none. It does not create the network and it does not prune unused ones.

## What the scripts change

`./scripts/setup.sh`

- Does not start, stop, or remove containers. The old `docker rm` of `resto-paperless` and `resto-mealie` is gone.
- May create `/mnt/user/appdata/resto/{postgres,n8n,metabase,resto-core}` and the invoice inbox if they are missing.
- Fills empty marketing secrets in `.env`. It does not replace a password that is already set, and it does not print the values.
- Rewrites the Paperless, Mealie, and resto URL lines when those keys already exist.

`./scripts/preflight-marketing.sh`

- Reads memory, load, disk free space, `vm.max_map_count`, port binds, the Tailscale bind address, Docker networks, every container name and published port, Primary storage, Secondary storage, and ZFS record size per workload.
- Exits non-zero when a check fails. Writes nothing. Starts nothing. Does not change a dataset or a sysctl.

`./scripts/up-marketing.sh`

- Requires `--stage mautic`, `--stage postiz`, or `--stage dashboard`. With no stage it prints the three stages and exits. It does not start every service at once.
- `--dry-run` prints that stage and writes nothing.
- With `MARKETING_APPROVED=1`, runs preflight first. Only after preflight passes does it fill placeholder secrets, create that stage's directories under `/mnt/cache/appdata/surveycafe-marketing`, and start only that stage's services with `--no-recreate`.
- Mautic starts `mautic-mysql`, `mautic`, `mautic-cron`, and `mautic-worker`.
- Postiz stays stopped unless `MARKETING_POSTIZ_APPROVED=1`. That approval also requires `vm.max_map_count=262144` for Elasticsearch. The script does not change the kernel.
- The dashboard stays stopped unless `MARKETING_DASHBOARD_APPROVED=1`. Its database lives on the Postiz Postgres instance. That stage does not start the Postiz application.
- Snapshots every container that marketing does not own, including the live Paperless, Mealie, and media containers. If any of those change id or state, the script exits 4.
- Joins the existing Docker network `resto`. If that network is missing, it stops. It does not create a bridge.
- Does not run `docker rm`, `compose down`, or `compose up` against `compose.yml`.
- Does not start `compose.public-edge.yml`.
- After a successful stage, `measure-marketing.sh` records memory, load, disk, and container stats.

`--no-recreate` keeps a container that already exists. A later change to `POSTIZ_URL` or `POSTIZ_DISABLE_REGISTRATION` does not enter that container until you remove that one marketing container and run its stage again.

`./scripts/up-public-edge.sh` starts only `resto-marketing-edge` after `MARKETING_PUBLIC_APPROVED=1`. It needs two DNS names and an ACME email. It does not publish the dashboard.

`./scripts/backup-marketing.sh` dumps Mautic MySQL as root, the Postiz database, the dashboard database, and each Temporal database with `pg_dump --clean --if-exists`. It refuses a destination inside `APPDATA` and refuses to exec into a protected container. Default on Unraid is `/mnt/user/backups/resto-marketing`. It does not dump `resto-postgres` and does not stop containers. That dump does not include the marketing `.env`.

`./scripts/backup-marketing-env.sh` encrypts the checkout `.env`. That file stays in `/mnt/cache/projects/resto-marketing`, outside appdata, and it holds the database passwords and `COMMAND_SECRET_KEY`. The ciphertext is AES-256-CBC with PBKDF2 (600000 iterations) and a salt. It is written to `/mnt/user/backups/resto-marketing/env/STAMP` when that backups directory exists, mode 600, outside the source checkout and outside `APPDATA`. The passphrase is `MARKETING_ENV_PASSPHRASE` in the environment for that one command. The script does not write the passphrase or the plaintext. `./scripts/restore-marketing-env.sh` decrypts it back to the checkout `.env` only, mode 600, and leaves an existing file in place unless `MARKETING_ENV_RESTORE_OVERWRITE=1`.

`./scripts/restore-marketing.sh` loads those dumps into the matching marketing containers only. A failed `docker exec` stops the script. `scripts/test-restore-isolated.sh` repeats this against throwaway `marketingtest-*` containers and refuses to run when `/mnt/user` exists.

`./scripts/rollback-marketing.sh` removes only the marketing container names. Every other container is compared before and after. Data directories stay unless `MARKETING_ROLLBACK_DELETE_DATA=1`, and that flag can delete only `mautic`, `postiz`, `temporal`, `command`, and `caddy` under the marketing `APPDATA`.

## Deploy

The production checkout is `/mnt/cache/appdata/resto` on `main` at `111fceefdb904828f56c761fb873d1222753b5af`, with local changes. Leave it there. Do not run `git checkout`, `git pull`, `git reset`, or `git clean` in that directory, and do not run `setup.sh` from the marketing checkout.

Marketing source and data are two directories on the NVMe pool:

- source: `/mnt/cache/projects/resto-marketing`
- data: `/mnt/cache/appdata/surveycafe-marketing`

`scripts/clone-marketing-source.sh` clones a detached checkout of `cursor/marketing-deploy-safety-7375` into the source directory and checks that it contains `95aa65bc110b6baa8aec840d5f824f684b8f4d5f` and the stacked marketing commit `cc57ca5d18222ef51114f6937a60bc9ac6c163f1`. It does not run git against the production tree. Compose files under `./docker` stay in the source checkout. Database and upload directories come from `APPDATA`.

When the host has no `python3`, an approved run unpacks CPython 3.12.12 into the source checkout's `.tools` directory. That is not a system package. The archive is `cpython-3.12.12+20260127-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`, sha256 `1c9b8720a71f810a04352dc82667ebd7757a565f46e9a7770215a80049582184`.

The first approved stage is Mautic only:

```bash
cd /mnt/cache/projects/resto-marketing
cp .env.example .env
chmod 600 .env
# APPDATA is already /mnt/cache/appdata/surveycafe-marketing
# BIND_ADDR is already 100.116.48.120
# HOME_MARKET is quoted. These scripts source .env with Bash.
./scripts/check-marketing-firstrun.sh
MARKETING_APPROVED=1 ./scripts/up-marketing.sh --stage mautic
# Set MARKETING_ENV_PASSPHRASE in this shell first. Keep it out of .env and out of git.
MARKETING_ENV_BACKUP_APPROVED=1 ./scripts/backup-marketing-env.sh
```

`check-marketing-firstrun.sh` copies `.env.example` to a temporary directory, sources that copy in an isolated shell, and runs `docker compose config`. It does not write the checkout `.env` and it does not start a container. A later run is safe after `/mnt/cache/appdata/surveycafe-marketing` exists: the checker fails only when compose config creates a directory that was not already there.

`scripts/deploy-mautic-phase1.sh` is the Mautic-only install. It checks that the checkout contains `d82e03f39aaa74d34c59ea009d7a4b8fb15a170a`, runs preflight, and stops without writing `.env` or starting a container when RAM, CPU, the resto network, storage, or port 8084 fails. The only containers it starts are Mautic, MySQL, cron, and the worker. Set `MARKETING_ENV_PASSPHRASE` in the shell before the run when the encrypted backup should be created in the same step. The passphrase is not written on the server. Run the env backup after the up script fills the placeholder passwords if it was not set. The passphrase has to be at least 16 characters. Store it outside the server. A later database dump still does not contain this file.

Postiz and the dashboard are separate approvals. The public Caddy file stays unstarted. `BIND_ADDR` must be the Tailscale address. `127.0.0.1` is refused on Unraid because a phone cannot open it. `0.0.0.0` and a LAN address are refused.

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
MARKETING_ENV_BACKUP_APPROVED=1 ./scripts/backup-marketing-env.sh
```

Restore into containers that are already running. Set `MARKETING_ENV_PASSPHRASE` in the shell before the env restore:

```bash
MARKETING_RESTORE_APPROVED=1 ./scripts/restore-marketing.sh /mnt/user/backups/resto-marketing/STAMP
MARKETING_ENV_RESTORE_APPROVED=1 MARKETING_ENV_RESTORE_OVERWRITE=1 \
  ./scripts/restore-marketing-env.sh /mnt/user/backups/resto-marketing/env/STAMP
```

Uploaded images and Mautic media live in the appdata directories. The SQL dumps do not replace those files. Keep the Unraid appdata backup for them. The env restore writes only the marketing checkout `.env`. It does not write into `/mnt/cache/appdata/resto`.

## Dashboard

React, TypeScript, and Tailwind, served by the FastAPI app. One owner session. Light and dark. The Connections page lists every integration with the proof we actually have. `live_verified` and `authorized_api_test` stay false until that platform accepts a call made with your credentials. Unit tests stub HTTP. Overview reachability is a local probe. It is not a completed post, email, or listing update.

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
