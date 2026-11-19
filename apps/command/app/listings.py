from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.hours import google_regular_hours, google_special_hours
from app.models import BusinessProfile
from app.remote import Remote, interpret
from app.vault import get_secret

STAR = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def _id(value: str, prefix: str) -> str:
    value = (value or "").strip()
    if value.startswith(prefix):
        return value.split("/", 1)[1]
    return value


def push_google(db: Session, profile: BusinessProfile, hours: dict, holidays: list) -> Remote:
    token = get_secret(db, "google_access_token")
    location = _id(get_secret(db, "google_location_id") or "", "locations/")
    if not token or not location:
        return Remote(False, 0, None, "Google access token or location id is not saved")
    body: dict = {}
    mask: list[str] = []
    if profile.location_name.strip():
        body["title"] = profile.location_name.strip()
        mask.append("title")
    if profile.description.strip():
        body["profile"] = {"description": profile.description.strip()}
        mask.append("profile.description")
    if profile.phone.strip():
        body["phoneNumbers"] = {"primaryPhone": profile.phone.strip()}
        mask.append("phoneNumbers")
    if profile.website.strip():
        body["websiteUri"] = profile.website.strip()
        mask.append("websiteUri")
    regular = google_regular_hours(hours)
    if regular is not None:
        body["regularHours"] = regular
        mask.append("regularHours")
    special = google_special_hours(holidays)
    if special is not None:
        body["specialHours"] = special
        mask.append("specialHours")
    if not mask:
        return Remote(False, 0, None, "Nothing to send. Add a description, phone, website, or at least one open day.")
    url = f"https://mybusinessbusinessinformation.googleapis.com/v1/locations/{location}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.patch(
                url,
                params={"updateMask": ",".join(mask)},
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def pull_google_reviews(db: Session) -> Remote:
    token = get_secret(db, "google_access_token")
    account = _id(get_secret(db, "google_account_id") or "", "accounts/")
    location = _id(get_secret(db, "google_location_id") or "", "locations/")
    if not token or not account or not location:
        return Remote(False, 0, None, "Google token, account id, and location id are required to read reviews")
    url = f"https://mybusiness.googleapis.com/v4/accounts/{account}/locations/{location}/reviews"
    reviews: list = []
    page = None
    try:
        with httpx.Client(timeout=30) as client:
            for _ in range(5):
                params = {"pageSize": 50}
                if page:
                    params["pageToken"] = page
                response = client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
                parsed = interpret(response)
                if not parsed.ok:
                    return parsed
                payload = parsed.payload if isinstance(parsed.payload, dict) else {}
                reviews.extend(payload.get("reviews") or [])
                page = payload.get("nextPageToken")
                if not page:
                    break
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return Remote(True, 200, {"reviews": reviews}, "OK")


def reply_google_review(db: Session, review_name: str, comment: str) -> Remote:
    token = get_secret(db, "google_access_token")
    if not token:
        return Remote(False, 0, None, "Google access token is not saved")
    if "/reviews/" not in review_name:
        return Remote(False, 0, None, "This review has no Google review id, so a reply cannot be sent")
    url = f"https://mybusiness.googleapis.com/v4/{review_name}/reply"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.put(url, headers={"Authorization": f"Bearer {token}"}, json={"comment": comment})
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def google_review_rows(payload: object) -> list[dict]:
    raw = payload.get("reviews") if isinstance(payload, dict) else None
    rows = []
    for review in raw or []:
        if not isinstance(review, dict):
            continue
        rating = review.get("starRating")
        rows.append(
            {
                "external_id": review.get("name") or review.get("reviewId") or "",
                "author": ((review.get("reviewer") or {}).get("displayName")) or "Google reviewer",
                "rating": float(STAR.get(rating, 0)),
                "body": review.get("comment") or "",
                "reviewed_at": review.get("createTime") or "",
            }
        )
    return [row for row in rows if row["external_id"]]


def pull_yelp_reviews(db: Session) -> Remote:
    key = get_secret(db, "yelp_api_key")
    business = get_secret(db, "yelp_business_id")
    if not key or not business:
        return Remote(False, 0, None, "Yelp API key or business id is not saved")
    url = f"https://api.yelp.com/v3/businesses/{business}/reviews"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return Remote(False, 0, None, exc.__class__.__name__)
    return interpret(response)


def yelp_review_rows(payload: object) -> list[dict]:
    raw = payload.get("reviews") if isinstance(payload, dict) else None
    rows = []
    for review in raw or []:
        if not isinstance(review, dict) or not review.get("id"):
            continue
        rows.append(
            {
                "external_id": str(review["id"]),
                "author": ((review.get("user") or {}).get("name")) or "Yelp reviewer",
                "rating": float(review.get("rating") or 0),
                "body": review.get("text") or "",
                "reviewed_at": review.get("time_created") or "",
            }
        )
    return rows
