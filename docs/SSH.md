# Install on Unraid over SSH

You are already on the server: `ssh root@100.116.48.120` lands on `root@lerouxfamily`. Paperless **and Mealie** are already running there. This install starts only the missing pieces: resto-core (wine cellar), n8n, Metabase, and a Postgres for those apps.

Do **not** install a second Paperless or a second Mealie.

## Paste this on Unraid (`root@lerouxfamily`)

```bash
curl -fsSL https://raw.githubusercontent.com/paulcrepin76-star/c/main/scripts/on-unraid-install.sh | bash
```

Then open:

- http://100.116.48.120:8088 — wine cellar
- your existing Paperless URL
- your existing Mealie URL
- http://100.116.48.120:5678 — n8n
- http://100.116.48.120:3001 — Metabase

## Existing Gmail invoices were not moved

The prompt required exactly `MOVE`. You typed `Move`. To file them now:

```bash
/mnt/user/appdata/resto/scripts/paperless/move-existing.sh
```
