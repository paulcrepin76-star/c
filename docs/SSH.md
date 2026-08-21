# Install on Unraid over SSH

You are already on the server: `ssh root@100.116.48.120` lands on `root@lerouxfamily`. Paperless is already running there. Do **not** install a second Paperless.

`ssh admin@100.116.48.120` failed because Unraid’s SSH user is `root`, and Tailscale tried to look up a local user named `admin`.

The SSH key was created **on Unraid** (`/root/.ssh/...`), not on the Mac. That is fine. Stay in the `root@lerouxfamily` session and install from there.

## Paste this on Unraid (`root@lerouxfamily`)

```bash
curl -fsSL https://raw.githubusercontent.com/paulcrepin76-star/c/main/scripts/on-unraid-install.sh | bash
```

Or, if git is installed:

```bash
mkdir -p /mnt/user/appdata
cd /mnt/user/appdata
git clone https://github.com/paulcrepin76-star/c.git resto
cd resto
chmod +x scripts/*.sh scripts/paperless/*.sh
./scripts/on-unraid-install.sh
```

That starts **resto-core, Mealie, n8n, Metabase** next to your current Paperless. It will not create `resto-paperless`.

Then open:

- http://100.116.48.120:8088 — wine cellar
- your existing Paperless URL
- http://100.116.48.120:9925 — Mealie
- http://100.116.48.120:5678 — n8n
- http://100.116.48.120:3001 — Metabase

## Existing Gmail invoices were not moved

The prompt required exactly `MOVE`. You typed `Move`, so files stayed put. Storage path, workflow, and saved views were still created.

To file the invoices now:

```bash
cd /mnt/user/appdata/resto
./scripts/paperless/move-existing.sh
```

## Paperless that is already working

Keep using it. Gmail label `Paperless-Invoices` (433 PDFs) and rule `Import Gmail PDF invoices` are the source of truth. resto-core only reads costing data from that archive.
