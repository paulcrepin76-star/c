from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.remote import Remote, interpret
from app.vault import get_secret

GOOGLE_QUERY = (
    "SELECT campaign.name, metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions "
    "FROM campaign WHERE segments.date DURING LAST_30_DAYS"
)


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _micros_to_cents(value) -> int:
    return int(round(int(value) / 10_000))


def _money_to_cents(value) -> int:
    return int(round(float(value) * 100))


def pull_google_ads(db: Session) -> Remote:
    token = get_secret(db, "google_ads_access_token")
    developer = get_secret(db, "google_ads_developer_token")
    customer = _digits(get_secret(db, "google_ads_customer_id"))
    if not token or not developer or not customer:
        return Remote(False, 0, None, "Google Ads token, developer token, and customer id are required")
    version = settings.google_ads_api_version.strip("/")
    url = f"https://googleads.googleapis.com/{version}/customers/{customer}/googleAds:search"
    headers = {"Authorization": f"Bearer {token}", "developer-token": developer}
    login = _digits(get_secret(db, "google_ads_login_customer_id"))
    if login:
        headers["login-customer-id"] = login
    try:
        with httpx.Client(timeout=40) as client:
            response = client.post(url, headers=headers, json={"query": GOOGLE_QUERY})
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def google_ads_rows(payload: object) -> list[dict]:
    batches = payload if isinstance(payload, list) else [payload]
    rows = []
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        for result in batch.get("results") or []:
            if not isinstance(result, dict):
                continue
            metrics = result.get("metrics") or {}
            cost = metrics.get("costMicros", metrics.get("cost_micros"))
            if cost is None:
                continue
            conversions = metrics.get("conversions")
            rows.append(
                {
                    "campaign_name": (result.get("campaign") or {}).get("name") or "Campaign",
                    "spend_cents": _micros_to_cents(cost),
                    "clicks": int(metrics.get("clicks") or 0),
                    "impressions": int(metrics.get("impressions") or 0),
                    "conversions": float(conversions) if conversions is not None else 0.0,
                    "detail": "",
                }
            )
    return rows


def pull_meta_ads(db: Session) -> Remote:
    token = get_secret(db, "meta_access_token")
    account = _digits(get_secret(db, "meta_ad_account_id"))
    if not token or not account:
        return Remote(False, 0, None, "Meta access token and ad account id are required")
    version = settings.meta_graph_version.strip("/")
    url = f"https://graph.facebook.com/{version}/act_{account}/insights"
    try:
        with httpx.Client(timeout=40) as client:
            response = client.get(
                url,
                params={
                    "fields": "campaign_name,spend,impressions,clicks,actions",
                    "date_preset": "last_30d",
                    "level": "campaign",
                    "access_token": token,
                },
            )
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def meta_ads_rows(payload: object) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = []
    for item in data or []:
        if not isinstance(item, dict) or "spend" not in item:
            continue
        conversions = 0.0
        noted = ""
        actions = item.get("actions")
        if not actions:
            noted = "Meta omitted actions on this row; conversions are stored as 0."
        else:
            for action in actions:
                kind = str(action.get("action_type") or "")
                if kind == "purchase" or "conversion" in kind:
                    conversions += float(action.get("value") or 0)
        rows.append(
            {
                "campaign_name": item.get("campaign_name") or "Campaign",
                "spend_cents": _money_to_cents(item["spend"]),
                "clicks": int(float(item.get("clicks") or 0)),
                "impressions": int(float(item.get("impressions") or 0)),
                "conversions": conversions,
                "detail": noted,
            }
        )
    return rows


def recommendations(latest: list[dict]) -> list[dict]:
    notes = []
    grouped: dict[str, list[dict]] = {}
    for row in latest:
        grouped.setdefault(row["platform"], []).append(row)
    for platform, rows in grouped.items():
        spend = sum(row["spend_cents"] for row in rows)
        conversions = sum(row["conversions"] or 0 for row in rows)
        if spend > 0 and conversions == 0:
            notes.append(
                {
                    "platform": platform,
                    "text": f"{platform} reported spend and zero conversions in the latest pull.",
                }
            )
    return notes
