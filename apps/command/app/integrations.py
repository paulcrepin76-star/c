"""What has actually been proven for each integration.

live_verified stays false in this report. A saved secret is not a successful call,
and a unit test that stubs HTTP is not a call to Google, Meta, Yelp, or Mautic.
"""

from __future__ import annotations

PROOFS: list[dict] = [
    {
        "id": "mautic",
        "name": "Mautic",
        "code": "implemented",
        "verification": "not_run_live",
        "unit_test": "No test in this workspace calls Mautic. Campaign creation code exists and leaves campaigns unpublished.",
        "still_needed": "Mautic 7.2.2 running, API enabled, and a basic-auth user or OAuth client saved in Settings. Then create one unpublished campaign and confirm Mautic returns the id.",
    },
    {
        "id": "postiz",
        "name": "Postiz",
        "code": "implemented",
        "verification": "unit_test",
        "unit_test": "A missing API key leaves the post as a draft. The mapper marks PUBLISHED only when that state string is present. The test does not open a Postiz server.",
        "still_needed": "Postiz v2.26.0 running, a public API key, and a connected channel. A post is published only after Postiz returns state PUBLISHED or a release URL.",
    },
    {
        "id": "n8n",
        "name": "n8n",
        "code": "implemented",
        "verification": "unit_test",
        "unit_test": "The announce endpoint rejects a missing API key and stores a draft. It does not import or execute an n8n workflow.",
        "still_needed": "Run scripts/import-marketing-workflows.sh on the server. The importer adds inactive workflows and does not change the Square, Mealie, or Paperless workflows.",
    },
    {
        "id": "google",
        "name": "Google Business Profile",
        "code": "implemented",
        "verification": "unit_test",
        "unit_test": "A stubbed HTTP 403 stays rejected with no confirmed time. A stubbed HTTP 200 is stored as confirmed. Google was not contacted.",
        "still_needed": "An OAuth access token for the Google account that manages the location, scope business.manage, and the location id. A private owner app can stay in Google Cloud testing mode.",
    },
    {
        "id": "google_ads",
        "name": "Google Ads",
        "code": "implemented",
        "verification": "not_run_live",
        "unit_test": "The client is in the source tree. This workspace has no unit test that returns live spend, and no developer token.",
        "still_needed": "Google must approve a developer token. A test token only sees a test account. Sync stores rows only from the API response.",
    },
    {
        "id": "meta_ads",
        "name": "Meta Ads",
        "code": "implemented",
        "verification": "not_run_live",
        "unit_test": "The insights client is in the source tree. No Meta token has been used from this workspace.",
        "still_needed": "A user token with ads_read and the ad account id. A development app can read accounts owned by its admins. Other users need App Review.",
    },
    {
        "id": "facebook",
        "name": "Facebook",
        "code": "partial",
        "verification": "unit_test",
        "unit_test": "Posts are sent only through the Postiz client. The unit test stops when the Postiz key is missing.",
        "still_needed": "A Meta app, FACEBOOK_APP_ID and FACEBOOK_APP_SECRET for Postiz, the Page connected inside Postiz, and a public HTTPS URL for OAuth. Page admins can use a development app. pages_manage_posts needs App Review for anyone else.",
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "code": "partial",
        "verification": "unit_test",
        "unit_test": "A text-only Instagram post is refused before any network call.",
        "still_needed": "A professional Instagram account linked to a Page, media on the post, and the same Postiz Meta app. instagram_content_publish needs App Review for a live app.",
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "code": "partial",
        "verification": "not_run_live",
        "unit_test": "Video-only rules exist in the Postiz client. No TikTok request has been made.",
        "still_needed": "TikTok must approve the Content Posting app. Set TIKTOK_CLIENT_ID and TIKTOK_CLIENT_SECRET, connect the account in Postiz, and send an MP4.",
    },
    {
        "id": "yelp",
        "name": "Yelp",
        "code": "partial",
        "verification": "unit_test",
        "unit_test": "A profile push stays manual. An approved reply is still unavailable and is not sent. The read client for three excerpts has not been called.",
        "still_needed": "A Fusion API key and business id for the read-only excerpt pull. Hours, photos, and replies stay in Yelp for Business.",
    },
    {
        "id": "apple",
        "name": "Apple Business Connect",
        "code": "not_implemented",
        "verification": "not_implemented",
        "unit_test": "There is no Apple client. Listing edits stay on this server.",
        "still_needed": "Apple has to approve an API integration before hours or showcases can be pushed. That client is not written.",
    },
    {
        "id": "tripadvisor",
        "name": "Tripadvisor",
        "code": "not_implemented",
        "verification": "manual",
        "unit_test": "There is no Tripadvisor client. Pushes are not offered as confirmed.",
        "still_needed": "A partner agreement would only add read access. Listing edits and review replies stay in the Management Center.",
    },
    {
        "id": "ollama",
        "name": "Local AI drafts",
        "code": "implemented",
        "verification": "not_run_live",
        "unit_test": "With no model configured, review drafts are labeled template. Menu text and text PDFs are parsed locally and that parser is tested.",
        "still_needed": "Set OLLAMA_BASE_URL and OLLAMA_TEXT_MODEL to draft replies on the server. A vision model is optional for menu photos. Nothing is sent to a cloud model.",
    },
]


def report() -> dict:
    return {
        "live_calls_made": False,
        "note": (
            "Nothing in this report contacted Google, Meta, Yelp, Tripadvisor, Apple, TikTok, Mautic, or Postiz. "
            "Unit tests stub HTTP. A saved credential is not a successful sync. "
            "authorized_api_test stays false until that platform accepts a call made with your credentials. "
            "Reachability on the overview is a separate local probe and does not mean a post, email, or listing was accepted."
        ),
        "integrations": [
            {**row, "live_verified": False, "authorized_api_test": False}
            for row in PROOFS
        ],
    }
