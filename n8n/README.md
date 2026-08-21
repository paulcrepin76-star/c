# n8n jobs for the restaurant stack

n8n is the only place that should hold Square tokens, mailbox passwords, or a portal login. resto-core never needs those secrets.

## Nightly flow

1. Schedule: 02:10 every night.
2. Square node: list payments / orders since yesterday for your location.
3. Map each line to JSON:

```json
{
  "sold_at": "2026-08-20T21:14:00",
  "name": "Sauvignon Blanc glass",
  "qty": 1,
  "unit_price": 11,
  "revenue": 11,
  "square_order_id": "abc",
  "square_line_id": "def",
  "square_item_id": "sq-item-id",
  "costing_group": "wine"
}
```

4. HTTP Request POST `http://resto-core:8080/api/sales/import`
   - Header `X-API-Key: $RESTO_API_KEY`
5. Optional: Mealie GET `/api/recipes` then POST recipe lines later.
6. HTTP Request POST `http://resto-core:8080/api/jobs/nightly`

## Paperless flow

Paperless already fetches email PDFs if you add a mail account in its UI (Settings → Mail).

When you want line items in costing:

1. Paperless webhook or n8n watch `/files/invoices-inbox`
2. POST `http://resto-core:8080/api/webhooks/paperless`

```json
{
  "id": "123",
  "title": "FPL August",
  "correspondent": "FPL",
  "created": "2026-08-18",
  "invoice_number": "12345",
  "total": 412.10,
  "invoice_type": "utility",
  "lines": []
}
```

Wine and Sam's Club invoices should include `lines` so bottle costs and ingredient prices update.

## Portal logins (last resort)

Only if the supplier does not email a PDF:

1. Create an n8n credential for that site.
2. Use the HTTP or browser node to download the bill.
3. Write the file to `/files/invoices-inbox`.
4. Paperless consumes it. You never store the password in this git repo.

If a site uses 2FA or CAPTCHA, keep it manual: download once, drop the PDF in the Unraid folder.
