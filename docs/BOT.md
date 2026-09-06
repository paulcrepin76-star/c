# Text the server

`grok-bot` is a small container on the stack. You text it from your phone and it answers about the restaurant and the server, and it installs, restarts, and updates containers when you tell it to.

It uses **Grok** (xAI) to understand what you wrote, and **Telegram** to carry the message. Telegram is the important half: the server polls out to `api.telegram.org`, so Unraid needs no open port, no public URL, and no reverse proxy. Nothing on the internet can reach the server through this.

```text
   your phone                  the internet                 Unraid
  ┌──────────┐   message   ┌──────────────────┐  outbound  ┌───────────────┐
  │ Telegram │ ──────────► │ api.telegram.org │ ◄───────── │   grok-bot    │
  └──────────┘             └──────────────────┘  long poll │  (port 8090)  │
                                                            │      │        │
                                    ┌───────────────────────┘      │        │
                              api.x.ai (Grok decides what to do)    │        │
                                                                    ▼        │
                                             docker.sock · compose · resto-core
                                                            └───────────────┘
```

## Set it up once

### 1. A Grok key

Go to [console.x.ai](https://console.x.ai), create an API key, and put it in `.env` on Unraid:

```bash
XAI_API_KEY=xai-...
GROK_MODEL=grok-4.6
```

Without a key the bot still works, but only with the plain commands at the bottom of this page. With a key you can write it like a person: *"is anything broken tonight?"*, *"why did n8n stop?"*, *"mets à jour tout"*.

### 2. A Telegram bot

1. Open Telegram on your phone and message **@BotFather**.
2. Send `/newbot`, pick a name (Survey Cafe) and a username ending in `bot`.
3. BotFather replies with a token like `8123456789:AAH...`. Put it in `.env`:

```bash
TELEGRAM_BOT_TOKEN=8123456789:AAH...
```

### 3. Start it and pair your phone

```bash
cd /mnt/user/appdata/resto
docker compose up -d --build grok-bot
```

Text your new bot anything. It answers with your chat id, because it does not know you yet:

> This bot is not paired yet. Your chat id is 546231908.

Put that number in `.env` and restart it:

```bash
TELEGRAM_ALLOWED_CHAT_IDS=546231908
```

```bash
docker compose up -d grok-bot
```

Now it answers you, and only you. Add more numbers separated by commas for a manager's phone.

## What to text it

**How are things**

> Today $1,240 on 63 tickets. Month to date $28,400, food 31.4%, wine 26.1%. The prep fridge has been at 46F for two hours — everything else is in range. Three bills still need a category.

It reads that from resto-core, the same numbers as the home page. It never invents a figure.

**How is the server**

> 11 of 12 containers running. Disk 62% used, 900 GB free. resto-metabase exited four minutes ago; everything else is up.

**Why is something down**

> "why did metabase stop"

It pulls the last log lines and tells you what it sees.

**Install an app**

> "install ntfy"
>
> I am about to install ntfy. Reply yes to run it, no to drop it.
>
> "yes"
>
> Installed ntfy from binwiederhier/ntfy:latest. Open http://100.116.48.120:8055

Text `apps` for the list it knows: ntfy, uptime-kuma, dozzle, homepage, ollama, adminer, filebrowser, vaultwarden. Anything else works too — give it an image and a port: *"install louislam/uptime-kuma:1 on port 3011"*.

**Update**

> "update" — git pull the repo, rebuild, restart the whole stack.
>
> "update n8n" — pull a newer image for one container only.

**Sync now**

> "sync" — pull Square sales, Paperless invoices, and Mealie recipes without waiting for tonight's job.

## Short commands are exact, sentences go to Grok

A message of three words or fewer that looks like a command runs exactly as written, without asking the model anything. `restart n8n` restarts n8n. `install ntfy` installs ntfy on its catalog port. `status` gives the restaurant board. These are instant, free, and always mean the same thing.

Anything longer is a question, and Grok answers it — *"why did metabase stop last night?"*, *"is the walk-in cold enough?"*, *"mets à jour n8n s'il te plaît"*.

## The safety rules

- **Only your chat ids get answers.** Everyone else gets one sentence and nothing else. Leave `TELEGRAM_ALLOWED_CHAT_IDS` empty and the bot refuses to do anything at all — it only tells you your id.
- **Nothing changes without a yes.** Restart, stop, start, install, remove, update: each one comes back as *"I am about to X. Reply yes to run it."* The pending action expires after ten minutes. Set `BOT_REQUIRE_CONFIRM=false` if you ever want it to stop asking.
- **Everything it does is written down.** `/mnt/user/appdata/resto/grok-bot/actions.log` gets one JSON line per tool it ran, with the chat it came from. `curl -H "X-API-Key: $RESTO_API_KEY" http://100.116.48.120:8090/actions` shows the last twenty.
- **The bot holds the docker socket.** That is what lets it restart and install things, and it is real power. It is why the allowlist and the confirmation exist. Do not publish port 8090 outside Tailscale.
- **Installs stay declarative.** A new app is written into `compose.extra.yml` next to `compose.yml`, so `docker compose up -d` keeps it running later. That file is not in git — it is the state of your server. Delete a block and run compose again to remove an app by hand.

## In a browser instead

`http://100.116.48.120:8088/assistant` is the same assistant in the cellar app, useful from the Mac. It talks to the same container, so a `yes` there does the same thing a `yes` on the phone does.

## If you would rather use SMS

Telegram is free and needs nothing open. Real SMS needs a public URL, so it means Twilio plus Tailscale Funnel or a reverse proxy. The endpoint exists if you want it: point a Twilio number's webhook at `https://your-public-host/sms` (POST) and put your mobile number in `TELEGRAM_ALLOWED_CHAT_IDS`. Telegram is the easier path and does not cost per message.

## The command list

These run exactly as written, with or without a Grok key, and they are the fallback the night xAI is unreachable:

| Text | What happens |
| --- | --- |
| `status` | Sales, food and wine cost, fridges, what needs you |
| `server` | Every container, disk, memory |
| `logs n8n` | Last lines from one container |
| `apps` | What it can install |
| `install ntfy` | Add an app, after a yes |
| `restart n8n` · `stop n8n` · `start n8n` | After a yes |
| `update` | Whole stack, after a yes |
| `update n8n` | One container, after a yes |
| `sync` | Pull Square, Paperless, and Mealie now |
| `help` | This list |
| `forget` | Drop the conversation and start clean |

## When it does not answer

```bash
docker logs --tail 50 resto-grok-bot
curl -s http://127.0.0.1:8090/health | jq
```

`health` tells you the three things that usually go wrong:

- `"grok": false` — no `XAI_API_KEY`.
- `"telegram": {"running": false}` — no token, or the token is wrong. `last_error` says which.
- `"docker": false` — the socket is not mounted, so it can answer about the restaurant but cannot touch containers.
