# n8n for Survey Cafe

You do not build the workflows. They are already imported.

You only add logins.

1. Open http://100.116.48.120:5678 and sign in as `surveycafedowntown@gmail.com`.
2. Left menu → **Credentials** → **Add credential** → **Header Auth**. Create these three names **exactly**:

| Credential name | Header name | Header value |
| --- | --- | --- |
| Square Access Token | Authorization | `Bearer` + your Square production access token |
| Mealie API | Authorization | `Bearer` + token from Mealie → profile → API tokens |
| Paperless Token | Authorization | `Token` + token from Paperless (port 8011) → user → API tokens |

3. Open workflow **Square sales → cellar**. Click **Square settings**. Replace `PASTE_SQUARE_LOCATION_ID` with your Square Location ID. Save. Toggle **Active**.
4. Toggle **Active** on **Mealie recipes → cellar** and **Paperless invoices → cellar**.
5. Open **Check cellar connection** and click **Test workflow**. It should return resto-core health.

Paperless already imports Gmail PDFs. n8n only copies those documents into costing. Square sales run every night at 02:10.
