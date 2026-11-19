from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.models import Audit, Secret

SECRET_FIELDS = [
    {"group": "Mautic", "name": "mautic_api_base", "label": "API base URL", "secret": False, "hint": "Inside Docker this is http://mautic. Leave blank to use that."},
    {"group": "Mautic", "name": "mautic_auth", "label": "Auth mode", "secret": False, "hint": "basic or oauth2"},
    {"group": "Mautic", "name": "mautic_username", "label": "API username or client id", "secret": True, "hint": ""},
    {"group": "Mautic", "name": "mautic_password", "label": "API password or client secret", "secret": True, "hint": ""},
    {"group": "Postiz", "name": "postiz_api_base", "label": "API base URL", "secret": False, "hint": "Inside Docker this is http://postiz:5000. Leave blank to use that."},
    {"group": "Postiz", "name": "postiz_api_key", "label": "Public API key", "secret": True, "hint": "Postiz Settings → Developers. Sent as the Authorization value, without Bearer."},
    {"group": "Google Business Profile", "name": "google_access_token", "label": "OAuth access token", "secret": True, "hint": "Scope business.manage"},
    {"group": "Google Business Profile", "name": "google_account_id", "label": "Account id", "secret": False, "hint": "The number from accounts/123, or the full resource name."},
    {"group": "Google Business Profile", "name": "google_location_id", "label": "Location id", "secret": False, "hint": "The number from locations/456, or the full resource name."},
    {"group": "Google Ads", "name": "google_ads_access_token", "label": "OAuth access token", "secret": True, "hint": ""},
    {"group": "Google Ads", "name": "google_ads_developer_token", "label": "Developer token", "secret": True, "hint": "Explorer access only sees test accounts."},
    {"group": "Google Ads", "name": "google_ads_customer_id", "label": "Customer id", "secret": False, "hint": "Digits only. Dashes are stripped."},
    {"group": "Google Ads", "name": "google_ads_login_customer_id", "label": "Manager customer id", "secret": False, "hint": "Only if the account sits under a manager account."},
    {"group": "Meta Ads", "name": "meta_access_token", "label": "Access token", "secret": True, "hint": "Needs ads_read."},
    {"group": "Meta Ads", "name": "meta_ad_account_id", "label": "Ad account id", "secret": False, "hint": "Digits only. act_ is added for you."},
    {"group": "Yelp", "name": "yelp_api_key", "label": "Fusion API key", "secret": True, "hint": "Read-only. Review excerpts, not the full history."},
    {"group": "Yelp", "name": "yelp_business_id", "label": "Business id", "secret": False, "hint": ""},
]

ALLOWED_SECRETS = {row["name"] for row in SECRET_FIELDS}
PUBLIC_SECRETS = {row["name"] for row in SECRET_FIELDS if not row["secret"]}


def get_secret(db: Session, name: str) -> str | None:
    row = db.get(Secret, name)
    if row is None or not row.ciphertext:
        return None
    return decrypt(row.ciphertext)


def configured(db: Session, name: str) -> bool:
    return bool(get_secret(db, name))


def set_secret(db: Session, name: str, value: str) -> None:
    if name not in ALLOWED_SECRETS:
        raise ValueError(name)
    row = db.get(Secret, name)
    now = datetime.now(timezone.utc)
    if value == "":
        if row is not None:
            db.delete(row)
        return
    blob = encrypt(value)
    if row is None:
        db.add(Secret(name=name, ciphertext=blob, updated_at=now))
    else:
        row.ciphertext = blob
        row.updated_at = now


def audit(db: Session, action: str, detail: str) -> None:
    db.add(Audit(action=action, detail=detail[:500]))
