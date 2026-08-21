# Architecture

## The rule

Each tool does one job. Nothing scrapes a website unless email and APIs have failed.

| Tool | Job | Not its job |
| --- | --- | --- |
| Square | What sold, at what price | Recipes, cellar, invoices |
| Mealie | Food recipes and cocktails | Wine list, costing % |
| Paperless-ngx | Original PDF, OCR, search, archive | Margin math |
| n8n | Talk to Square / mail / rare portals | Store the cellar |
| resto-core | Products, wine, inventory, costing | Document vault |
| Postgres | Source of truth for numbers | PDFs |
| Metabase | Charts on a screen | Data entry |

## Why not one Invoice Fetcher that logs into everything

A dedicated FPL / Sam's Club / Chef's Warehouse / Comcast robot looks tidy on a whiteboard. In production it is a pile of brittle browser sessions:

- 2FA and “verify this device”
- CAPTCHA and anti-bot pages
- HTML changes that silently stop downloads
- Passwords copied into prompts or source code

Keep three layers instead:

1. **Email + consume folder** — Paperless already knows how to fetch mail and watch a directory. This covers utilities and most vendors.
2. **Official API** — Square for sales, Mealie for recipes. n8n stores the tokens.
3. **Portal job in n8n** — only for a vendor that never emails a PDF. The file still lands in Paperless. resto-core never sees the password.

## Data flow

```text
INTERNET
   │
   ├─ email PDFs ──────────────────────────────► Paperless
   ├─ drop folder /mnt/user/documents/invoices-inbox ─► Paperless
   ├─ Square API ─ n8n ─ /api/sales/import ────► resto-core
   └─ Mealie API ─ n8n / optional token ───────► resto-core recipes
                                                    │
                         wine products + pours      │
                         invoice line items         │
                         theoretical stock moves    │
                                                    ▼
                                                Postgres (resto)
                                                    │
                                                    ▼
                                                 Metabase
```

## Wine model

A wine is a `product` (category `wine`, base unit `ml`) plus a `wine_profile` (vintage, pour, bin, par).

It can have two `sellable_items`:

- glass: 150 ml, Square item “Sauvignon Blanc glass”
- bottle: 750 ml, Square item “Sauvignon Blanc bottle”

Cocktails are `recipes` with `recipe_lines` pointing at wine / spirit / juice products, then one sellable mapped to Square. That is the only time wine belongs in Mealie.

Inventory is a running sum of `stock_moves`:

- `receive` from an invoice or the cellar form
- `sale` from Square (negative ml)
- `count_adjust` after a physical count
- later: `waste`, `comp`, `breakage`

Food cost, beverage cost and wine cost are theoretical until you count. After a count, variance is counted minus expected.

## Secrets

`.env` on the Unraid share holds Postgres, Paperless, n8n and resto-core keys.

Square / mailbox / portal passwords stay in n8n credentials or in `.env` on the server. They are not in this repository and they should not be pasted into a chat.
