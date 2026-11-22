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
./scripts/map-count-unraid.sh
```

That command prints the current value and changes nothing. It exits 3. Apply the change only with a separate approval:

```bash
MARKETING_MAP_COUNT_APPROVED=1 ./scripts/map-count-unraid.sh
```

With that approval the script reads `/boot/config/go` first. It reports an `exit` or `return` that would skip a line added at the end of the file. It keeps a single `sysctl -w vm.max_map_count=262144` before any of those statements, and it removes an older whole-line setting instead of leaving two values. A statement that sets `vm.max_map_count` in a more complicated way stops the script before it writes. The original `go` file is copied to `/boot/config/go.pre-marketing-mapcount` before the rewrite. The script reads that result back and checks it. Only then does it change the running kernel value. Unraid rebuilds `/etc` at boot, so a line in `/etc/sysctl.conf` does not survive a reboot. `/boot/config/go` is on the flash drive and does.

Restore the original boot file, and only then the saved running value:

```bash
./scripts/map-count-rollback.sh
MARKETING_MAP_COUNT_ROLLBACK_APPROVED=1 ./scripts/map-count-rollback.sh
```

The first of those exits 3 and changes nothing. Phase 2 does not call either script and unsets `MARKETING_MAP_COUNT_APPROVED`.

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

`scripts/clone-marketing-source.sh` clones into the source directory and detaches HEAD at `MARKETING_DEPLOY_COMMIT`. That value has to be the full 40-character SHA. The script does not check out a branch tip. It checks that the commit contains `95aa65bc110b6baa8aec840d5f824f684b8f4d5f`, the stacked marketing commit `cc57ca5d18222ef51114f6937a60bc9ac6c163f1`, `d82e03f39aaa74d34c59ea009d7a4b8fb15a170a`, `e8f918406dd0b004e5d1c4ee64d4654ba4e03939`, and the Phase 1 installer `99b5b0dd3d54ba5752d710a84d53e7c02449c748`. It does not run git against the production tree. Compose files under `./docker` stay in the source checkout. Database and upload directories come from `APPDATA`.

When the host has no `python3`, `scripts/deploy-mautic-phase1.sh` unpacks CPython 3.12.12 into the source checkout's `.tools` directory before the first-run check and before preflight. That is not a system package. The archive is `cpython-3.12.12+20260127-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`, sha256 `1c9b8720a71f810a04352dc82667ebd7757a565f46e9a7770215a80049582184`.

The first approved stage is Mautic only:

```bash
cd /mnt/cache/projects/resto-marketing
# MARKETING_DEPLOY_COMMIT is the full 40-character SHA. Do not check out the branch tip.
git fetch origin cursor/marketing-deploy-safety-7375
git checkout --detach "$MARKETING_DEPLOY_COMMIT"
test "$(git rev-parse HEAD)" = "$MARKETING_DEPLOY_COMMIT"
# Optional: export MARKETING_ENV_PASSPHRASE in this shell. It is not written on the server.
MARKETING_PHASE1_APPROVED=1 ./scripts/deploy-mautic-phase1.sh
```

`check-marketing-firstrun.sh` copies `.env.example` to a temporary directory, sources that copy in an isolated shell, and runs `docker compose config`. It does not write the checkout `.env` and it does not start a container. A later run is safe after `/mnt/cache/appdata/surveycafe-marketing` exists: the checker fails only when compose config creates a directory that was not already there.

`scripts/deploy-mautic-phase1.sh` is the Mautic-only install. Set `MARKETING_DEPLOY_COMMIT` to the full SHA that was checked out. The script refuses a branch name and refuses a HEAD that is not that SHA. It also requires `e8f918406dd0b004e5d1c4ee64d4654ba4e03939` to be contained in that commit. It bootstraps private Python, runs preflight, and stops without writing `.env` or starting a container when RAM, CPU, the resto network, storage, or port 8084 fails. The only containers it starts are Mautic, MySQL, cron, and the worker.

Exit status:

| Code | Meaning |
| --- | --- |
| 0 | Mautic is healthy on the Tailscale port and the encrypted `.env` backup was verified. |
| 1 | Refused before Docker. The commit, `APPDATA`, or `BIND_ADDR` was wrong. No container was started. |
| 2 | Preflight or the first-run check failed. No container was started. |
| 3 | `MARKETING_PHASE1_APPROVED` was not set. Nothing was started. |
| 4 | Partial installation. Docker was invoked and the install did not finish. The state of every marketing container is printed. |
| 5 | Installation succeeded. No passphrase was supplied, so the encrypted backup was not created. This is not a failed installation. |
| 6 | A passphrase was supplied and rejected before Docker. Nothing was started. The passphrase is not printed. |
| 7 | Installation succeeded, but the encrypted backup could not be created or verified. This is not a failed installation. |

Set `MARKETING_ENV_PASSPHRASE` in the shell before the run when the backup should be created in the same step. It must be at least 16 characters. The script verifies that it can encrypt and decrypt a sample, then verifies the real backup checksum and mode `600`. The passphrase is not printed and is not written on the server. Store it outside the server. A later database dump still does not contain this file.

Postiz is the second approval. The dashboard and the public Caddy file stay unstarted. `BIND_ADDR` must be the Tailscale address. `127.0.0.1` is refused on Unraid because a phone cannot open it. `0.0.0.0` and a LAN address are refused.

`MAUTIC_TRUSTED_PROXIES` is the JSON array `[]`. Mautic is opened directly on Tailscale, so it trusts no proxy. A bare CIDR is not valid JSON and Mautic refuses to start. Phase 2 corrects that one line in the existing `.env` when it is not a JSON array, and it does not recreate the Mautic containers. When public HTTPS is approved later, set `MAUTIC_TRUSTED_PROXIES='["172.29.0.0/16"]'` and recreate only Mautic. That recreate is not part of Phase 2.

Phase 2 is `scripts/deploy-postiz-phase2.sh`. Set `MARKETING_DEPLOY_COMMIT` to the full SHA that was checked out. The script refuses a branch name. HEAD must contain the Phase 1 installer `99b5b0dd3d54ba5752d710a84d53e7c02449c748`. The script requires the existing `.env`, a passphrase of at least 16 characters, and a healthy Mautic. It dumps `resto-mautic-mysql` and encrypts the original `.env` before it reads or writes `MAUTIC_TRUSTED_PROXIES`. A value that is already a JSON array is left unchanged. An invalid value is replaced with `[]` only after that original backup has been verified, and the Mautic containers are not recreated. New Postiz secrets are filled after that backup, and a second encrypted copy is verified. Existing Mautic passwords are not replaced. It then runs the Postiz preflight. `vm.max_map_count` below 262144 stops the run. The script does not change that setting.

The only containers it starts are `resto-postiz`, `resto-postiz-postgres`, `resto-postiz-redis`, `resto-marketing-db-init`, `resto-temporal`, `resto-temporal-postgres`, `resto-temporal-elasticsearch`, and `resto-temporal-ui`. Postiz is published on `100.116.48.120:4007`. Temporal UI stays on `127.0.0.1:8085`. The empty `command` database is created for later and `resto-command` is not started.

Phase 2 exit status:

| Code | Meaning |
| --- | --- |
| 0 | Postiz, Temporal, Elasticsearch, Postgres, and Redis are healthy. Mautic is still healthy and its container ids are unchanged. Backups were verified before the start. |
| 1 | Refused before Phase 2 Docker changes. The commit, `.env`, paths, or Mautic health check failed. No Phase 2 container was started. |
| 2 | Preflight failed, including `vm.max_map_count`, RAM, the resto network, storage, or ports. No Phase 2 container was started. Mautic was not recreated. |
| 3 | `MARKETING_PHASE2_APPROVED` was not set. Nothing was started. |
| 4 | Partial Phase 2 installation. Docker was invoked and the install did not finish, or a Mautic container id changed. The state of every marketing container is printed. |
| 6 | The backup passphrase was missing or rejected. Nothing was started. The passphrase is not printed. |
| 7 | The Mautic database backup or the encrypted configuration backup could not be created or verified. Phase 2 was not started. Mautic was not recreated. |

There is no exit 5. Phase 2 does not continue without a verified backup.

Phase 3 is `scripts/deploy-dashboard-phase3.sh`. It starts only `resto-command` on `100.116.48.120:8090` after Mautic and Postiz are healthy. It backs up the Mautic and Postiz databases and encrypts the working `.env` before preflight. It checks that the `command` role can read the `command` database on the existing Postiz Postgres. If that database is missing, it creates the role and database with `docker exec` and does not recreate `resto-postiz-postgres`. `docker compose` is called with `--no-deps --no-recreate` for the `command` service only. Mautic, Postiz, Temporal, production containers, `vm.max_map_count`, ZFS, Docker networks, and Caddy stay untouched. `scripts/rollback-dashboard-phase3.sh` removes only `resto-command`.

Phase 3 exit status:

| Code | Meaning |
| --- | --- |
| 0 | The dashboard answered on port 8090 and an unsigned `/api/me` was rejected. Existing container ids were unchanged. |
| 1 | Refused before the dashboard container was created. The commit, paths, health of Mautic or Postiz, or the command database check failed. |
| 2 | Preflight failed. `resto-command` was not started. |
| 3 | `MARKETING_PHASE3_APPROVED` was not set. Nothing was started. |
| 4 | Partial installation. Docker was invoked and the dashboard did not finish, or another container id changed. |
| 6 | The backup passphrase was missing or rejected. Nothing was started. |
| 7 | A database backup or the encrypted configuration backup could not be verified. The dashboard was not started. |

Phase 3 is not ready to run on the server until two checks are true. `resto-temporal` has to be healthy, not merely running. Its healthcheck is `temporal operator cluster health --address 127.0.0.1:7233`. A five-second Docker timeout made that command look failed while the process was still starting, so the timeout in `compose.marketing.yml` is 15 seconds and the start period is 90 seconds. Applying that compose change restarts nothing by itself. Do not recreate Temporal until you approve a later deploy. Postiz answering on port 4007 is not the public API authentication test. That test stays unresolved until a saved public API key is accepted by `/api/public/v1/integrations`. The dashboard does not treat homepage reachability as that success.

The homepage reads stored reports for the selected 7, 30, 90, or custom dates. Advertising spend, campaign clicks, published posts, and dated Google or Yelp reviews appear only when those records exist. Reservations, marketing-attributed revenue, and ROI stay unavailable. Mautic's contact total is stored only by Refresh and is never shown as new contacts. A scheduled post is not counted as published. Each figure names its source. A comparison appears only when the previous window has the same kind of observation, and green or red is used only for a direction that has a meaning.

The dashboard reads Mautic and Postiz with credentials saved in its own encrypted store. Those calls are real HTTP requests. A page stays empty when the API has not answered. Sending a campaign and publishing a post stay behind separate buttons, and campaign activation from this dashboard is refused. Ollama is used only when `OLLAMA_BASE_URL` and `OLLAMA_TEXT_MODEL` are set. The installer does not start or change Ollama containers. n8n workflows are not imported by Phase 3.

Social accounts stay disconnected in this phase. Meta, TikTok, and the other OAuth providers reject a Tailscale URL. Postiz builds each redirect as `{FRONTEND_URL}/integrations/social/{provider}`. For a later public name `https://social.example.com` the callbacks are:

| Provider | Redirect URI | Credentials already in `.env` |
| --- | --- | --- |
| Facebook Page | `https://social.example.com/integrations/social/facebook` | `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` |
| Instagram through the Facebook Business | `https://social.example.com/integrations/social/instagram` | the same Facebook app |
| Instagram standalone | `https://social.example.com/integrations/social/instagram-standalone` | `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` |
| TikTok | `https://social.example.com/integrations/social/tiktok` | `TIKTOK_CLIENT_ID`, `TIKTOK_CLIENT_SECRET` |

Those values stay empty until the developer apps exist. TikTok also requires HTTPS for media fetch, a public privacy policy, and Login Kit plus Content Posting API. DNS, Caddy, and `POSTIZ_URL=https://social.example.com` are a later approval. Phase 2 does not request a certificate and does not publish port 80 or 443.

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

Caddy is `caddy:2.10.2-alpine`. It proxies those two names to Postiz and Mautic on the Docker network. Direct Tailscale access keeps `MAUTIC_TRUSTED_PROXIES='[]'`. After the certificate exists, set `MAUTIC_TRUSTED_PROXIES='["172.29.0.0/16"]'`, recreate only the Mautic containers, and set the Mautic site URL to `https://mail.example.com` inside Mautic. Set `POSTIZ_URL` to the public Postiz origin before connecting a social account, then recreate only the Postiz container when you are ready for it to pick up the new URL.

## Rollback

Phase 2 rollback removes only the Postiz and Temporal containers. Mautic keeps running and `APPDATA/mautic` is kept:

```bash
MARKETING_PHASE2_ROLLBACK_APPROVED=1 ./scripts/rollback-postiz-phase2.sh
```

Add `MARKETING_PHASE2_ROLLBACK_DELETE_DATA=1` only when the Postiz and Temporal directories should also be removed. That flag does not delete `APPDATA/mautic`.

`scripts/rollback-marketing.sh` is the full marketing rollback. It removes Mautic as well. It is not the Phase 2 procedure.

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
