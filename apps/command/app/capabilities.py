"""What each platform actually allows a private restaurant install to do.

These labels are the contract the dashboard uses. A screen may say "confirmed"
only after the destination returns a success response. "manual" means the owner
updates the site themselves. "approval" means an official API exists and the
platform must approve the app or developer token before it will work.
"""

from __future__ import annotations

CAPABILITIES: list[dict] = [
    {
        "id": "google",
        "name": "Google Business Profile",
        "group": "listing",
        "listing_write": "supported",
        "review_read": "supported",
        "review_reply": "supported",
        "posts": "supported",
        "summary": "Hours, description, photos, local posts, and review replies are available to a manager of the location through the Business Profile APIs.",
        "requirements": "OAuth token for the Google account that manages the location, scope https://www.googleapis.com/auth/business.manage, plus the account and location ids. A private app used only by the owner can stay in Google Cloud testing mode. A public app needs Google verification.",
    },
    {
        "id": "apple",
        "name": "Apple Business Connect",
        "group": "listing",
        "listing_write": "approval",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "approval",
        "summary": "Apple Business Connect can update hours, photos, and showcases after Apple approves API access. There is no review inbox in this API.",
        "requirements": "An approved Apple Business Connect API integration. Until that approval is in place, listing edits stay on this server.",
    },
    {
        "id": "yelp",
        "name": "Yelp",
        "group": "listing",
        "listing_write": "manual",
        "review_read": "read",
        "review_reply": "manual",
        "posts": "unavailable",
        "summary": "The public Fusion API can read a business and up to three review excerpts. It cannot change hours, photos, or the menu, and it cannot publish a review response.",
        "requirements": "A Yelp Fusion API key and the business id for the read-only excerpt pull. Responses are written in Yelp for Business.",
    },
    {
        "id": "tripadvisor",
        "name": "Tripadvisor",
        "group": "listing",
        "listing_write": "manual",
        "review_read": "approval",
        "review_reply": "manual",
        "posts": "unavailable",
        "summary": "Tripadvisor's Content API is a partner read API. Owners update the listing and answer reviews in the Management Center. This dashboard does not pretend to post there.",
        "requirements": "A partner agreement for any read access. Day-to-day edits stay manual.",
    },
    {
        "id": "facebook",
        "name": "Facebook",
        "group": "social",
        "listing_write": "unavailable",
        "review_read": "approval",
        "review_reply": "approval",
        "posts": "supported",
        "summary": "Page posts go through Postiz once the Facebook app and Page are connected there. This dashboard records the post as published only when Postiz reports state PUBLISHED or returns a release URL.",
        "requirements": "A Meta app. Page admins can use it in development mode. pages_manage_posts needs App Review before anyone else can use the app. Postiz also needs FACEBOOK_APP_ID and FACEBOOK_APP_SECRET.",
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "group": "social",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "supported",
        "summary": "Publishing needs an Instagram professional account linked to a Facebook Page, and a photo or video. Postiz sends the post. Text-only Instagram posts are refused here.",
        "requirements": "The same Meta app as Facebook, plus instagram_content_publish for a live app. Connect the account inside Postiz.",
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "group": "social",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "approval",
        "summary": "TikTok posting is video-only and goes through Postiz after TikTok audits the developer app. A photo or caption without a video is not submitted.",
        "requirements": "TikTok Content Posting API approval, TIKTOK_CLIENT_ID and TIKTOK_CLIENT_SECRET in the Postiz environment, and the account connected in Postiz.",
    },
    {
        "id": "google_ads",
        "name": "Google Ads",
        "group": "ads",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "unavailable",
        "ads_read": "approval",
        "summary": "Campaign cost, clicks, impressions, and conversions can be read after Google approves a developer token. Test tokens only see test accounts. This screen does not invent spend.",
        "requirements": "OAuth access token, developer token, and the customer id (no dashes). Basic or standard access is required for a production account.",
    },
    {
        "id": "meta_ads",
        "name": "Meta Ads",
        "group": "ads",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "unavailable",
        "ads_read": "approval",
        "summary": "Ad insights can be read with ads_read. A development app can read accounts owned by its admins. Live use by other people needs App Review.",
        "requirements": "A Meta user token with ads_read and the ad account id.",
    },
    {
        "id": "mautic",
        "name": "Mautic",
        "group": "local",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "unavailable",
        "summary": "Email campaigns and contacts live in Mautic 7.2.2 on this server. The API user is created in Mautic, then saved here.",
        "requirements": "Mautic 7.2.2 running on MySQL 8.4, API enabled, and either basic auth or an OAuth2 client. Campaigns are created unpublished.",
    },
    {
        "id": "postiz",
        "name": "Postiz",
        "group": "local",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "supported",
        "summary": "Postiz is the social publisher. The public API key is created in Postiz under Settings, Developers. The key is sent as the Authorization header with no Bearer prefix. The public API allows about 30 requests an hour.",
        "requirements": "Postiz running, at least one channel connected, and the public API key saved in Settings.",
    },
    {
        "id": "n8n",
        "name": "n8n",
        "group": "local",
        "listing_write": "unavailable",
        "review_read": "unavailable",
        "review_reply": "unavailable",
        "posts": "unavailable",
        "summary": "Existing n8n stays as it is. New marketing workflows call this dashboard with the resto API key. They are imported inactive and do not change the Square, Mealie, or Paperless workflows.",
        "requirements": "n8n on the resto Docker network. Import n8n/marketing with scripts/import-marketing-workflows.sh when you want the timers.",
    },
]

BY_ID = {row["id"]: row for row in CAPABILITIES}
LISTING_PLATFORMS = ["google", "apple", "yelp", "tripadvisor"]


def capability(platform: str) -> dict | None:
    return BY_ID.get(platform)


def mode(platform: str, field: str) -> str:
    row = BY_ID.get(platform) or {}
    return row.get(field) or "unavailable"
