# Install on Unraid over SSH

Yes — that is the right way to let the agent (or you) put the stack on the server.

This Cursor cloud machine is **not** on your home network. It cannot SSH to `192.168.x.x` or `tower.local` unless Unraid is reachable on the public internet or through Tailscale/WireGuard.

Never paste the Unraid root password into chat. Use an SSH key.

## Option A — you already SSH from a laptop (easiest)

On that laptop:

```bash
ssh-copy-id root@YOUR_UNRAID_IP
cd /path/to/this-repo
./scripts/deploy-unraid.sh root@YOUR_UNRAID_IP
```

That rsyncs the files to `/mnt/user/appdata/resto`, writes a local `.env` with random secrets, and runs `docker compose up`.

Then open:

- http://YOUR_UNRAID_IP:8088 — wine cellar
- http://YOUR_UNRAID_IP:8010 — Paperless
- http://YOUR_UNRAID_IP:9925 — Mealie
- http://YOUR_UNRAID_IP:5678 — n8n
- http://YOUR_UNRAID_IP:3001 — Metabase

## Option B — let the cloud agent SSH in

1. Install Tailscale (or WireGuard) on Unraid so the hostname is reachable from the internet.
2. Add an SSH public key under Unraid **Settings → Management Access** (or `~/.ssh/authorized_keys` for root).
3. Send only:
   - `root@your-unraid.tailnet.ts.net`
   - not the password

Then the agent can run `./scripts/deploy-unraid.sh root@your-unraid.tailnet.ts.net`.

## Option C — SSH one-liner if the repo is already on Unraid

```bash
ssh root@YOUR_UNRAID_IP
cd /mnt/user/appdata/resto
./scripts/setup.sh
./scripts/remote-up.sh
```

## After it is up

Still in the Unraid browser, not in chat:

1. Paperless → create admin → add the mailbox that receives e-bills
2. Mealie → create admin
3. resto-core → add real wines (demo bottles are already there)
4. n8n → Square credential → nightly sales import
5. Drop manual PDFs in `/mnt/user/documents/invoices-inbox`
