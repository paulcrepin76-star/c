# Install on Unraid over SSH

Yes — that is the right way to put the stack on the server.

This Cursor cloud machine is **not** on your Tailnet. Unraid is `root@100.116.48.120`. Deploy from the MacBook.

Never paste the Unraid root password into chat. Type it only in Terminal when `ssh-copy-id` asks once.

## Your Mac had no SSH key

`ssh-copy-id: ERROR: No identities found` means the laptop has never created a key. Do this in Terminal on **Pauls-MacBook-Pro**, not as `root@lerouxfamily`.

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "paulcrepin@Pauls-MacBook-Pro"
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@100.116.48.120
ssh root@100.116.48.120 'hostname && ls /mnt/user && docker info >/dev/null && echo ok'
```

`ssh-copy-id` will ask for the Unraid root password **once**. After `echo ok` works without a password, clone and deploy:

```bash
cd ~
git clone https://github.com/paulcrepin76-star/c.git resto-backoffice
cd resto-backoffice
./scripts/deploy-unraid.sh root@100.116.48.120
```

Then open:

- http://100.116.48.120:8088 — wine cellar
- http://100.116.48.120:8010 — Paperless
- http://100.116.48.120:9925 — Mealie
- http://100.116.48.120:5678 — n8n
- http://100.116.48.120:3001 — Metabase

If `ssh-copy-id` is missing on the Mac, use this instead:

```bash
cat ~/.ssh/id_ed25519.pub | ssh root@100.116.48.120 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

## Paperless storage path

Invoices are stored as:

`Survey Cafe/{{ created_year }}/{{ correspondent }}/{{ document_type }}/{{ created }} - {{ title }} - {{ doc_pk }}`

That layout is already set in `compose.yml`. After Paperless is up, you can also paste the same path in Paperless → Settings → Storage paths if you use the UI template.

## After it is up

Still in the browser, not in chat:

1. Paperless → create admin → add the mailbox that receives e-bills
2. Mealie → create admin
3. resto-core → add real wines (demo bottles are already there)
4. n8n → Square credential → nightly sales import
5. Drop manual PDFs in `/mnt/user/documents/invoices-inbox`
