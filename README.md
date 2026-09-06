# Restaurant back office on Unraid

Square sells. Mealie knows the recipes. Paperless files the invoices. The wine cellar tracks every bottle and every glass. Unraid puts the numbers next to each other so you can see food cost, wine cost, and margin without a spreadsheet.

## The short version

I want an automatic back office for the restaurant. It pulls Square sales, Mealie recipes, supplier invoices, and the wine cellar, then calculates food cost, beverage cost, wine cost, coefficient, and variance by itself. Metabase is the dashboard.

Encore plus court, en français :

Je veux un back-office automatique pour mon restaurant : Square, Mealie, Paperless et la cave à vin alimentent le serveur Unraid, qui calcule tout seul le coût matière, le coût vin, les marges et les stats.

## Why this is easier than a scraper for every supplier

The original idea (one Invoice Fetcher that logs into FPL, Sam's Club, Chef's Warehouse, Comcast, etc.) works, but it is the expensive way. Portals break, 2FA appears, CAPTCHAs block the bot, and you end up maintaining a browser script per vendor.

Do this instead:

| Priority | Method | Use it for |
| --- | --- | --- |
| 1 | Email PDF → Paperless | Almost every invoice, including utilities |
| 2 | Official API / CSV | Square sales, Mealie recipes |
| 3 | Drop folder on the share | Anything you still download by hand |
| 4 | Portal automation in n8n | Last resort, one site at a time |

Paperless is the filing cabinet. n8n talks to the outside world and holds secrets. **resto-core** is the MarginEdge-style board for costing, invoices, and wine.

```text
  FPL / Sam's / Chef's / wine invoices / utilities
                    │
            email PDF or drop folder
                    ▼
              Paperless-ngx          Mealie recipes
                    │                      │
                    ▼                      ▼
                 n8n  ────── Square sales ──►  resto-core
                                               │
                                    wine cellar │ food recipes
                                    glasses     │ invoice lines
                                               ▼
                                           Postgres
                                               ▼
                                            Metabase
```

You do **not** give supplier passwords to this git repo. Log in yourself on the cellar Connect page.

## Wine belongs here, not in Mealie

Mealie stays for food recipes and for mixed drinks (sangria, cocktails). A bottle of Sancerre is not a recipe. It is a product with a purchase price, a pour size, a Square item, and a bin number.

Example:

- Bottle = 750 ml, cost $15
- Pour = 150 ml → 5 theoretical glasses
- Cost per glass = $3.00
- Sell at $11.00 → wine cost 27.3%, coefficient 3.67

If Square sold 40 glasses, expected usage is 6,000 ml = 8 bottles. The next inventory count tells you whether the bar over-poured, comped, spilled, or lost bottles.

Beer, coffee, and juice use the same math later. The cellar UI is built for wine first.

## What runs on Unraid

One Compose stack, one Postgres, these containers:

| Container | Port | Role |
| --- | --- | --- |
| resto-core | 8088 | Wine cellar, inventory, costing, purchasing |
| paperless-ngx | 8010 | Invoice PDF archive + OCR |
| mealie | 9925 | Recipes |
| n8n | 5678 | Square / mail / rare portal jobs |
| metabase | 3001 | Dashboards |
| grok-bot | 8090 | Grok assistant you text from your phone |
| postgres | 5433 | Shared database server |

On Unraid (`ssh root@100.116.48.120`) Paperless and Mealie are already running. Install only the missing pieces:

```bash
curl -fsSL https://raw.githubusercontent.com/paulcrepin76-star/c/main/scripts/on-unraid-install.sh | bash
```

Open `http://100.116.48.120:8088` for the cellar. This will not start a second Paperless or Mealie. Details: [docs/SSH.md](docs/SSH.md).

## What you do on day one

1. Keep using your existing Paperless and Mealie.
2. Open `http://100.116.48.120:8088/connect`. Click Connect on Square, Mealie, and Paperless, and log in with the accounts you already use.
3. In resto-core, add your real wines (or edit the demo list).
4. The home page at `http://100.116.48.120:8088` is the restaurant board: sales, food/wine cost, and graphs. Metabase at `http://100.116.48.120:3001` is optional extra reporting.
5. Drop any PDF you still download by hand into `/mnt/user/documents/invoices-inbox`.

You do **not** put tokens into n8n. n8n only runs the nightly sync after you have connected on that page.

## Text the server from your phone

`grok-bot` puts Grok on the stack and Telegram on your phone. You text it, it answers.

> **How are things?**
>
> Today $1,240 on 63 tickets. Month to date $28,400, food 31.4%, wine 26.1%. The prep fridge has been at 46F for two hours — everything else is in range. Three bills still need a category.

> **Install ntfy**
>
> I am about to install ntfy. Reply yes to run it, no to drop it.

It reads sales and fridges from resto-core, reads containers and disk from Docker, and installs, restarts, or updates anything on the stack — but only after you reply **yes**, and only for the chat ids you listed.

Two keys and one restart:

```bash
XAI_API_KEY=xai-...            # console.x.ai
TELEGRAM_BOT_TOKEN=8123...     # @BotFather in Telegram
```

```bash
docker compose up -d --build grok-bot
```

Telegram polls outbound, so nothing has to be open to the internet. The same assistant is at `http://100.116.48.120:8088/assistant` in a browser. Setup, safety rules, and the full command list: [docs/BOT.md](docs/BOT.md).
