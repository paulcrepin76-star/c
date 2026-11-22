from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import ads, ai, listings, mautic, postiz
from app.capabilities import LISTING_PLATFORMS, capability, mode
from app.config import settings
from app.hours import any_day_open, empty_hours, normalize_hours
from app.jsonutil import dump, load, stamp
from app.menu_extract import items_from_model_text, parse_menu_text, pdf_text
from app.models import (
    AdSnapshot,
    BusinessProfile,
    Campaign,
    Event,
    MenuDocument,
    MenuItem,
    Notification,
    Review,
    SocialPost,
    utcnow,
)
from app.probes import service_status
from app.vault import PUBLIC_SECRETS, SECRET_FIELDS, audit, configured, get_secret, set_secret

MEDIA_TYPES = postiz.IMAGE_TYPES | postiz.VIDEO_TYPES


def ensure_profiles(db: Session) -> None:
    existing = {row.platform for row in db.query(BusinessProfile).all()}
    for platform in LISTING_PLATFORMS:
        if platform in existing:
            continue
        db.add(
            BusinessProfile(
                platform=platform,
                location_name="Survey Café",
                hours_json=dump(empty_hours()),
                holiday_hours_json="[]",
                updated_at=utcnow(),
            )
        )
    db.commit()


def _notify(db: Session, title: str, body: str, level: str = "info") -> None:
    db.add(Notification(level=level, title=title, body=body, created_at=utcnow()))


def profile_out(row: BusinessProfile) -> dict:
    return {
        "platform": row.platform,
        "location_name": row.location_name,
        "description": row.description,
        "phone": row.phone,
        "website": row.website,
        "hours": normalize_hours(load(row.hours_json, {})),
        "holiday_hours": load(row.holiday_hours_json, []),
        "announcement": row.announcement,
        "sync_state": row.sync_state,
        "sync_detail": row.sync_detail,
        "confirmed_at": stamp(row.confirmed_at),
        "updated_at": stamp(row.updated_at),
        "capability": capability(row.platform),
    }


def save_profile(db: Session, platform: str, data: dict) -> dict:
    row = db.get(BusinessProfile, platform)
    if row is None or platform not in LISTING_PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown listing")
    row.location_name = (data.get("location_name") or "").strip()
    row.description = (data.get("description") or "").strip()
    row.phone = (data.get("phone") or "").strip()
    row.website = (data.get("website") or "").strip()
    row.hours_json = dump(normalize_hours(data.get("hours") or {}))
    row.holiday_hours_json = dump(data.get("holiday_hours") or [])
    row.announcement = (data.get("announcement") or "").strip()
    row.sync_state = "draft"
    row.sync_detail = "Saved on this server. Nothing has been sent."
    row.confirmed_at = None
    row.confirmed_payload = ""
    row.updated_at = utcnow()
    audit(db, "profile.save", platform)
    db.commit()
    return profile_out(row)


def push_profile(db: Session, platform: str) -> dict:
    row = db.get(BusinessProfile, platform)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown listing")
    hours = normalize_hours(load(row.hours_json, {}))
    holidays = load(row.holiday_hours_json, [])
    write = mode(platform, "listing_write")
    announcement_note = ""
    if row.announcement.strip():
        announcement_note = " The announcement stays here until you publish it from Social."
    if write == "manual":
        row.sync_state = "manual"
        row.sync_detail = (capability(platform) or {})["summary"] + announcement_note
        row.updated_at = utcnow()
        audit(db, "profile.push", f"{platform} manual")
        db.commit()
        return profile_out(row)
    if write == "unavailable":
        row.sync_state = "manual"
        row.sync_detail = "This platform has no listing API for this install." + announcement_note
        row.updated_at = utcnow()
        db.commit()
        return profile_out(row)
    if write == "approval":
        row.sync_state = "draft"
        row.sync_detail = (capability(platform) or {})["requirements"] + announcement_note
        row.updated_at = utcnow()
        audit(db, "profile.push", f"{platform} approval required")
        db.commit()
        return profile_out(row)
    if not any_day_open(hours):
        hours_note = " Hours were not included because every day is marked closed."
    else:
        hours_note = ""
    result = listings.push_google(db, row, hours, holidays)
    row.updated_at = utcnow()
    if result.ok:
        row.sync_state = "confirmed"
        row.confirmed_at = utcnow()
        row.confirmed_payload = dump(result.payload)[:20000]
        row.sync_detail = "Google accepted the location update." + hours_note + announcement_note
        audit(db, "profile.push", f"{platform} confirmed")
    else:
        row.sync_state = "rejected" if result.status_code else "draft"
        row.confirmed_at = None
        row.confirmed_payload = ""
        row.sync_detail = result.detail + hours_note + announcement_note
        audit(db, "profile.push", f"{platform} {row.sync_state}")
    db.commit()
    return profile_out(row)


def _store_blob(filename: str, blob: bytes) -> str:
    folder = Path(settings.data_dir) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name or "upload"
    path = folder / f"{uuid.uuid4().hex}-{safe}"
    path.write_bytes(blob)
    return str(path)


def add_menu_file(db: Session, filename: str, content_type: str, blob: bytes) -> dict:
    if len(blob) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Files are limited to 15 MB")
    stored = _store_blob(filename, blob)
    text = ""
    detail = ""
    status = "stored"
    items: list[dict] = []
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind in {"text/plain", "text/csv"} or filename.lower().endswith((".txt", ".csv")):
        text = blob.decode("utf-8", errors="replace")
        items = parse_menu_text(text)
        status = "extracted" if items else "no_items"
        detail = f"{len(items)} priced lines read from the file."
    elif kind == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            text = pdf_text(blob)
        except Exception as exc:  # noqa: BLE001
            text = ""
            detail = f"Could not read the PDF ({exc.__class__.__name__})."
            status = "error"
        else:
            items = parse_menu_text(text)
            status = "extracted" if items else "no_text"
            if not text.strip():
                detail = "The PDF has no text layer. A photo and a vision model, or a text export, are required."
            else:
                detail = f"{len(items)} priced lines read from the PDF text."
    elif kind.startswith("image/"):
        model_text, model_detail = ai.read_menu_image(blob)
        if model_text:
            text = model_text
            items = items_from_model_text(model_text)
            status = "extracted" if items else "no_items"
            detail = f"Vision model {model_detail} returned {len(items)} priced items."
        else:
            status = "stored"
            detail = model_detail
    else:
        status = "stored"
        detail = "This file type is stored only. Text, CSV, PDF, and images are the ones the reader understands."
    document = MenuDocument(
        filename=filename,
        media_type=kind,
        stored_path=stored,
        extracted_text=text[:50000],
        status=status,
        detail=detail,
        created_at=utcnow(),
    )
    db.add(document)
    db.flush()
    for item in items:
        db.add(
            MenuItem(
                document_id=document.id,
                name=item["name"][:200],
                description=item["description"],
                price_cents=item["price_cents"],
                confidence=item["confidence"],
                approved=False,
            )
        )
    audit(db, "menu.upload", f"{filename} {status}")
    db.commit()
    db.refresh(document)
    return document_out(document)


def document_out(row: MenuDocument) -> dict:
    return {
        "id": row.id,
        "filename": row.filename,
        "media_type": row.media_type,
        "status": row.status,
        "detail": row.detail,
        "created_at": stamp(row.created_at),
    }


def item_out(row: MenuItem) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "name": row.name,
        "description": row.description,
        "price_cents": row.price_cents,
        "category": row.category,
        "confidence": row.confidence,
        "approved": row.approved,
    }


def update_item(db: Session, item_id: int, data: dict) -> dict:
    row = db.get(MenuItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Menu item not found")
    if data.get("name") is not None:
        row.name = str(data["name"]).strip()[:200]
    if data.get("description") is not None:
        row.description = str(data["description"]).strip()
    if data.get("price_cents") is not None:
        price = int(data["price_cents"])
        if price < 0 or price > 100_000:
            raise HTTPException(status_code=400, detail="Price is out of range")
        row.price_cents = price
    if data.get("category") is not None:
        row.category = str(data["category"]).strip()[:80]
    if data.get("approved") is not None:
        row.approved = bool(data["approved"])
    db.commit()
    return item_out(row)


def post_out(row: SocialPost) -> dict:
    return {
        "id": row.id,
        "body": row.body,
        "channels": load(row.channels_json, []),
        "media": load(row.media_json, []),
        "scheduled_for": row.scheduled_for,
        "status": row.status,
        "postiz_id": row.postiz_id,
        "remote_state": row.remote_state,
        "release_url": row.release_url,
        "detail": row.detail,
        "created_at": stamp(row.created_at),
        "updated_at": stamp(row.updated_at),
    }


def create_post(db: Session, data: dict) -> dict:
    row = SocialPost(
        body=(data.get("body") or "").strip(),
        channels_json=dump(_clean_channels(data.get("channels") or [])),
        scheduled_for=(data.get("scheduled_for") or "").strip(),
        status="draft",
        detail="Saved on this server. Postiz has not received it.",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return post_out(row)


def update_post(db: Session, post_id: int, data: dict) -> dict:
    row = db.get(SocialPost, post_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if row.status == "published":
        raise HTTPException(status_code=409, detail="A published post is not edited here. Create a new one.")
    if "body" in data:
        row.body = (data.get("body") or "").strip()
    if "channels" in data:
        row.channels_json = dump(_clean_channels(data.get("channels") or []))
    if "scheduled_for" in data:
        row.scheduled_for = (data.get("scheduled_for") or "").strip()
    row.status = "draft"
    row.detail = "Saved on this server. Postiz has not received this version."
    row.updated_at = utcnow()
    db.commit()
    return post_out(row)


def _clean_channels(channels: list) -> list[dict]:
    cleaned = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        integration_id = str(channel.get("integration_id") or "").strip()
        provider = str(channel.get("provider") or "").strip()
        if integration_id and provider:
            cleaned.append({"integration_id": integration_id, "provider": provider, "name": channel.get("name") or provider})
    return cleaned


def attach_media(db: Session, post_id: int, filename: str, content_type: str, blob: bytes) -> dict:
    row = db.get(SocialPost, post_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Postiz accepts JPEG, PNG, GIF, WebP, AVIF, BMP, TIFF, and MP4.")
    if len(blob) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Media is limited to 50 MB")
    stored = _store_blob(filename, blob)
    media = load(row.media_json, [])
    media.append({"local_path": stored, "filename": Path(filename).name, "content_type": kind, "id": "", "path": ""})
    row.media_json = dump(media)
    row.updated_at = utcnow()
    db.commit()
    return post_out(row)


def submit_post(db: Session, post_id: int, mode: str) -> dict:
    row = db.get(SocialPost, post_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    channels = load(row.channels_json, [])
    if not channels:
        raise HTTPException(status_code=409, detail="Choose a connected Postiz channel first.")
    if not row.body.strip() and not load(row.media_json, []):
        raise HTTPException(status_code=400, detail="Write a caption or attach media.")
    if mode == "schedule" and not row.scheduled_for:
        raise HTTPException(status_code=400, detail="Pick a time, or use Publish now.")
    media = load(row.media_json, [])
    providers = {channel["provider"] for channel in channels}
    if providers & {"instagram", "instagram-standalone"} and not any(item["content_type"] in postiz.IMAGE_TYPES or item["content_type"] in postiz.VIDEO_TYPES for item in media):
        raise HTTPException(status_code=409, detail="Instagram needs a photo or video. Nothing was sent.")
    if "tiktok" in providers and not any(item["content_type"] in postiz.VIDEO_TYPES for item in media):
        raise HTTPException(status_code=409, detail="TikTok needs an MP4. Nothing was sent.")
    uploaded = []
    for item in media:
        if item.get("id") and item.get("path"):
            uploaded.append({"id": item["id"], "path": item["path"]})
            continue
        blob = Path(item["local_path"]).read_bytes()
        result = postiz.upload_file(db, item["filename"], item["content_type"], blob)
        if not result.ok or not isinstance(result.payload, dict):
            row.status = "draft"
            row.detail = f"Postiz did not accept the file. {result.detail}"
            row.updated_at = utcnow()
            db.commit()
            return post_out(row)
        item["id"] = str(result.payload.get("id") or "")
        item["path"] = str(result.payload.get("path") or "")
        upload_status = result.payload.get("status")
        if upload_status and upload_status != "ready":
            row.media_json = dump(media)
            row.status = "draft"
            row.detail = f"Postiz is still processing the file ({upload_status}). Wait until it is ready, then submit again."
            row.updated_at = utcnow()
            db.commit()
            return post_out(row)
        uploaded.append({"id": item["id"], "path": item["path"]})
    row.media_json = dump(media)
    body = postiz.build_create_body(channels, row.body, uploaded, row.scheduled_for, mode)
    result = postiz.request(db, "POST", "/posts", json=body)
    row.updated_at = utcnow()
    if not result.ok:
        row.status = "draft"
        row.detail = f"Postiz refused the post. {result.detail}"
        audit(db, "post.submit", f"{row.id} refused")
        db.commit()
        return post_out(row)
    payload = result.payload if isinstance(result.payload, dict) else {}
    remote_posts = payload.get("posts") if isinstance(payload.get("posts"), list) else []
    first = remote_posts[0] if remote_posts and isinstance(remote_posts[0], dict) else payload
    state = ""
    release = ""
    postiz_id = str(payload.get("id") or first.get("id") or "")
    if isinstance(first, dict):
        state = str(first.get("state") or "")
        release = str(first.get("releaseURL") or "")
        postiz_id = str(first.get("id") or postiz_id)
    row.postiz_id = postiz_id
    row.remote_state = state
    row.release_url = release
    row.status = "published" if state == "PUBLISHED" or release else postiz.map_remote_state(state)
    if row.status == "published":
        row.detail = "Postiz reports this post as published."
    elif row.status == "submitted":
        row.detail = "Postiz accepted the post. It is not marked published until Postiz reports PUBLISHED or a release URL."
    else:
        row.detail = f"Postiz returned state {state or 'unknown'}."
    audit(db, "post.submit", f"{row.id} {row.status}")
    db.commit()
    return post_out(row)


def refresh_posts(db: Session) -> dict:
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    result = postiz.request(
        db,
        "GET",
        "/posts",
        params={"startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
    )
    if not result.ok:
        return {"ok": False, "detail": result.detail, "updated": 0}
    payload = result.payload if isinstance(result.payload, dict) else {}
    remote = payload.get("posts") if isinstance(payload.get("posts"), list) else []
    by_id = {str(item.get("id")): item for item in remote if isinstance(item, dict) and item.get("id")}
    updated = 0
    for row in db.query(SocialPost).filter(SocialPost.postiz_id != "").all():
        item = by_id.get(row.postiz_id)
        if not item:
            continue
        row.remote_state = str(item.get("state") or "")
        row.release_url = str(item.get("releaseURL") or "")
        row.status = "published" if row.remote_state == "PUBLISHED" or row.release_url else postiz.map_remote_state(row.remote_state)
        if row.remote_state == "ERROR":
            row.detail = str(item.get("error") or "Postiz reported an error.")
        elif row.status == "published":
            row.detail = "Postiz reports this post as published."
        updated += 1
    db.commit()
    return {"ok": True, "detail": f"Matched {updated} posts with Postiz.", "updated": updated}


def delete_post(db: Session, post_id: int) -> dict:
    row = db.get(SocialPost, post_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if row.postiz_id:
        result = postiz.request(db, "DELETE", f"/posts/{row.postiz_id}")
        if not result.ok:
            row.detail = f"Postiz did not delete it. The local copy was kept. {result.detail}"
            db.commit()
            raise HTTPException(status_code=502, detail=row.detail)
    db.delete(row)
    db.commit()
    return {"deleted": True}


def list_channels(db: Session) -> dict:
    result = postiz.request(db, "GET", "/integrations")
    if not result.ok:
        return {"ok": False, "detail": result.detail, "channels": []}
    return {"ok": True, "detail": "Channels reported by Postiz.", "channels": postiz.integration_rows(result.payload)}


def campaign_out(row: Campaign) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "subject": row.subject,
        "body": row.body,
        "status": row.status,
        "mautic_id": row.mautic_id,
        "detail": row.detail,
        "updated_at": stamp(row.updated_at),
    }


def update_campaign(db: Session, campaign_id: int, data: dict) -> dict:
    row = db.get(Campaign, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if row.status == "mautic_published":
        raise HTTPException(
            status_code=409,
            detail="This campaign is published in Mautic. This dashboard does not edit or send it.",
        )
    if "name" in data and (data.get("name") or "").strip():
        row.name = data["name"].strip()
    if "subject" in data:
        row.subject = (data.get("subject") or "").strip()
    if "body" in data:
        row.body = (data.get("body") or "").strip()
    row.updated_at = utcnow()
    if row.mautic_id:
        result = mautic.request(
            db,
            "PATCH",
            f"/api/campaigns/{row.mautic_id}/edit",
            json={"name": row.name, "description": row.body, "isPublished": False},
        )
        if not result.ok:
            row.detail = f"Saved here. Mautic did not accept the draft update. {result.detail}"
        else:
            payload = result.payload if isinstance(result.payload, dict) else {}
            campaign = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else payload
            published = bool(campaign.get("isPublished"))
            row.status = "mautic_published" if published else "mautic_draft"
            row.detail = (
                "Mautic reports this campaign as published. This dashboard did not request that."
                if published
                else "Mautic accepted the draft update. The campaign is not published."
            )
    else:
        row.status = "local"
        row.detail = "Saved on this server. Mautic has not received it."
    audit(db, "campaign.edit", f"{row.id} {row.status}")
    db.commit()
    return campaign_out(row)


def create_campaign(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Campaign name is required")
    row = Campaign(
        name=name,
        subject=(data.get("subject") or "").strip(),
        body=(data.get("body") or "").strip(),
        status="local",
        detail="Saved on this server. Mautic has not received it.",
        updated_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return campaign_out(row)


def push_campaign(db: Session, campaign_id: int) -> dict:
    row = db.get(Campaign, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if row.status == "mautic_published":
        raise HTTPException(
            status_code=409,
            detail="This campaign is already published in Mautic. This dashboard does not send it.",
        )
    if row.mautic_id:
        return update_campaign(db, campaign_id, {"name": row.name, "subject": row.subject, "body": row.body})
    result = mautic.request(
        db,
        "POST",
        "/api/campaigns/new",
        json={"name": row.name, "description": row.body, "isPublished": False},
    )
    row.updated_at = utcnow()
    if not result.ok:
        row.status = "local"
        row.detail = f"Mautic did not create the campaign. {result.detail}"
        db.commit()
        return campaign_out(row)
    payload = result.payload if isinstance(result.payload, dict) else {}
    campaign = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else payload
    row.mautic_id = str(campaign.get("id") or "")
    published = bool(campaign.get("isPublished"))
    row.status = "mautic_published" if published else "mautic_draft"
    row.detail = (
        "Mautic created the campaign and reports it as published."
        if published
        else "Mautic created the campaign and it is not published."
    )
    audit(db, "campaign.push", f"{row.id} {row.status}")
    db.commit()
    return campaign_out(row)


def pull_campaigns(db: Session) -> dict:
    result = mautic.request(db, "GET", "/api/campaigns?limit=100")
    if not result.ok:
        return {"ok": False, "detail": result.detail, "campaigns": [campaign_out(row) for row in db.query(Campaign).all()]}
    seen = {row.mautic_id: row for row in db.query(Campaign).all() if row.mautic_id}
    for item in mautic.campaign_rows(result.payload):
        row = seen.get(item["id"])
        if row is None:
            row = Campaign(name=item["name"], updated_at=utcnow())
            db.add(row)
        row.name = item["name"]
        row.mautic_id = item["id"]
        row.status = "mautic_published" if item["published"] else "mautic_draft"
        row.detail = "Reported by Mautic."
        row.updated_at = utcnow()
    contacts = mautic.request(db, "GET", "/api/contacts?limit=1")
    total = mautic.contact_total(contacts.payload) if contacts.ok else None
    db.commit()
    return {
        "ok": True,
        "detail": "Mautic returned these campaigns.",
        "contacts": total,
        "campaigns": [campaign_out(row) for row in db.query(Campaign).order_by(Campaign.id.desc()).all()],
    }


def ad_rows(db: Session) -> list[dict]:
    rows = db.query(AdSnapshot).order_by(AdSnapshot.captured_at.desc(), AdSnapshot.id.desc()).all()
    latest: dict[tuple, AdSnapshot] = {}
    captured = {}
    for row in rows:
        captured.setdefault(row.platform, row.captured_at)
    current = []
    for row in rows:
        if row.captured_at != captured.get(row.platform):
            continue
        key = (row.platform, row.campaign_name)
        if key in latest:
            continue
        latest[key] = row
        current.append(
            {
                "platform": row.platform,
                "campaign_name": row.campaign_name,
                "spend_cents": row.spend_cents,
                "clicks": row.clicks,
                "impressions": row.impressions,
                "conversions": row.conversions,
                "currency": row.currency,
                "detail": row.detail,
                "captured_at": stamp(row.captured_at),
            }
        )
    return current


def sync_ads(db: Session) -> dict:
    messages = []
    stored = 0
    pulls = [("google_ads", ads.pull_google_ads, ads.google_ads_rows), ("meta_ads", ads.pull_meta_ads, ads.meta_ads_rows)]
    for platform, pull, parse in pulls:
        result = pull(db)
        if result.status_code == 0 and result.payload is None and "required" in result.detail:
            messages.append({"platform": platform, "ok": False, "detail": result.detail})
            continue
        if not result.ok:
            messages.append({"platform": platform, "ok": False, "detail": result.detail})
            continue
        parsed = parse(result.payload)
        now = utcnow()
        for item in parsed:
            db.add(
                AdSnapshot(
                    platform=platform,
                    campaign_name=item["campaign_name"][:200],
                    spend_cents=item["spend_cents"],
                    clicks=item["clicks"],
                    impressions=item["impressions"],
                    conversions=item["conversions"],
                    detail=item["detail"],
                    captured_at=now,
                )
            )
            stored += 1
        messages.append({"platform": platform, "ok": True, "detail": f"{len(parsed)} campaigns returned."})
    db.commit()
    latest = ad_rows(db)
    return {"results": messages, "stored": stored, "latest": latest, "recommendations": ads.recommendations(latest)}


def review_out(row: Review) -> dict:
    return {
        "id": row.id,
        "platform": row.platform,
        "external_id": row.external_id,
        "author": row.author,
        "rating": row.rating,
        "body": row.body,
        "reviewed_at": row.reviewed_at,
        "source": row.source,
        "draft_response": row.draft_response,
        "draft_source": row.draft_source,
        "approval": row.approval,
        "publish_state": row.publish_state,
        "publish_detail": row.publish_detail,
        "capability": capability(row.platform),
    }


def add_review(db: Session, data: dict) -> dict:
    platform = (data.get("platform") or "").strip()
    if capability(platform) is None:
        raise HTTPException(status_code=400, detail="Unknown platform")
    body = (data.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Review text is required")
    row = Review(
        platform=platform,
        external_id=f"manual-{uuid.uuid4().hex}",
        author=(data.get("author") or "").strip(),
        rating=float(data.get("rating") or 0),
        body=body,
        reviewed_at=(data.get("reviewed_at") or ""),
        source="manual",
        publish_state="not_sent",
        publish_detail="Entered here. It did not come from the platform.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return review_out(row)


def _upsert_reviews(db: Session, platform: str, rows: list[dict]) -> int:
    count = 0
    for item in rows:
        row = (
            db.query(Review)
            .filter(Review.platform == platform, Review.external_id == item["external_id"])
            .one_or_none()
        )
        if row is None:
            row = Review(platform=platform, external_id=item["external_id"], source=platform)
            db.add(row)
            count += 1
        row.author = item["author"][:160]
        row.rating = item["rating"]
        row.body = item["body"]
        row.reviewed_at = item["reviewed_at"]
        if row.source == "manual":
            row.source = platform
    return count


def pull_reviews(db: Session) -> dict:
    messages = []
    added = 0
    google = listings.pull_google_reviews(db)
    if google.ok:
        added += _upsert_reviews(db, "google", listings.google_review_rows(google.payload))
        messages.append({"platform": "google", "ok": True, "detail": "Google returned reviews."})
    else:
        messages.append({"platform": "google", "ok": False, "detail": google.detail})
    yelp = listings.pull_yelp_reviews(db)
    if yelp.ok:
        added += _upsert_reviews(db, "yelp", listings.yelp_review_rows(yelp.payload))
        messages.append(
            {
                "platform": "yelp",
                "ok": True,
                "detail": "Yelp returned its public excerpts. This is not the full review history, and replies cannot be posted from here.",
            }
        )
    else:
        messages.append({"platform": "yelp", "ok": False, "detail": yelp.detail})
    messages.append(
        {
            "platform": "tripadvisor",
            "ok": False,
            "detail": "Tripadvisor reviews are not pulled. The owner site is the Management Center.",
        }
    )
    db.commit()
    return {"results": messages, "added": added}


def draft_review(db: Session, review_id: int) -> dict:
    row = db.get(Review, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    draft = ai.review_draft(row.author, row.rating, row.body)
    row.draft_response = draft["text"]
    row.draft_source = draft["source"]
    row.approval = "pending"
    row.publish_detail = draft["detail"]
    db.commit()
    return review_out(row)


def set_review_approval(db: Session, review_id: int, approval: str, text: str | None) -> dict:
    row = db.get(Review, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if approval not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Approval must be pending, approved, or rejected")
    if text is not None:
        row.draft_response = text.strip()
        if row.draft_source == "ollama":
            row.draft_source = "human"
        elif not row.draft_source:
            row.draft_source = "human"
    row.approval = approval
    db.commit()
    return review_out(row)


def send_review(db: Session, review_id: int) -> dict:
    row = db.get(Review, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    reply = mode(row.platform, "review_reply")
    if reply != "supported":
        row.publish_state = "unavailable"
        row.publish_detail = (capability(row.platform) or {}).get("summary") or "Replies are not available."
        db.commit()
        return review_out(row)
    if row.approval != "approved":
        raise HTTPException(status_code=409, detail="Approve the reply before it can be sent.")
    if not row.draft_response.strip():
        raise HTTPException(status_code=400, detail="Write a reply first.")
    result = listings.reply_google_review(db, row.external_id, row.draft_response.strip())
    if result.ok:
        row.publish_state = "confirmed"
        row.publish_detail = "Google accepted the review reply."
        row.confirmed_payload = dump(result.payload)[:20000]
        audit(db, "review.send", f"{row.id} confirmed")
    else:
        row.publish_state = "not_sent"
        row.publish_detail = result.detail
        audit(db, "review.send", f"{row.id} not sent")
    db.commit()
    return review_out(row)


def event_out(row: Event) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "description": row.description,
        "capacity": row.capacity,
        "promo_text": row.promo_text,
        "promo_source": row.promo_source,
        "status": row.status,
        "updated_at": stamp(row.updated_at),
    }


def create_event(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Event name is required")
    row = Event(
        name=name,
        kind=(data.get("kind") or "dinner").strip()[:40],
        starts_at=(data.get("starts_at") or "").strip(),
        ends_at=(data.get("ends_at") or "").strip(),
        description=(data.get("description") or "").strip(),
        capacity=data.get("capacity"),
        status="draft",
        updated_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return event_out(row)


def update_event(db: Session, event_id: int, data: dict) -> dict:
    row = db.get(Event, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    for field in ("name", "kind", "starts_at", "ends_at", "description", "promo_text"):
        if field in data and data[field] is not None:
            setattr(row, field, str(data[field]).strip())
    if "capacity" in data:
        row.capacity = data["capacity"]
    if "promo_text" in data:
        row.promo_source = "human"
    row.updated_at = utcnow()
    db.commit()
    return event_out(row)


def promo_event(db: Session, event_id: int) -> dict:
    row = db.get(Event, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    promo = ai.event_promo(row.name, row.kind, row.starts_at, row.description)
    row.promo_text = promo["text"]
    row.promo_source = promo["source"]
    row.updated_at = utcnow()
    db.commit()
    return {**event_out(row), "detail": promo["detail"]}


def queue_event(db: Session, event_id: int) -> dict:
    row = db.get(Event, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    text = row.promo_text.strip() or f"{row.name} at Survey Café. {row.description}".strip()
    post = SocialPost(
        body=text,
        status="draft",
        scheduled_for=row.starts_at,
        detail="Draft created from the event. It has not been sent to Postiz.",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    campaign = Campaign(
        name=row.name,
        subject=row.name,
        body=text,
        status="local",
        detail="Draft created from the event. It has not been sent to Mautic.",
        updated_at=utcnow(),
    )
    db.add(post)
    db.add(campaign)
    row.status = "queued"
    row.updated_at = utcnow()
    _notify(db, row.name, "A social draft and an email draft are waiting. Neither has been published.", "info")
    audit(db, "event.queue", row.name)
    db.commit()
    db.refresh(post)
    db.refresh(campaign)
    return {"published": False, "event": event_out(row), "post": post_out(post), "campaign": campaign_out(campaign)}


def announce(db: Session, data: dict) -> dict:
    event = create_event(db, data)
    queued = queue_event(db, event["id"])
    return {"published": False, "event_id": event["id"], **queued}


def audience(db: Session) -> dict:
    if not (get_secret(db, "mautic_username") and get_secret(db, "mautic_password")):
        return {
            "ok": False,
            "contacts": None,
            "segments": None,
            "detail": "Mautic API credentials are not saved. No contact or segment count is shown.",
        }
    contacts = mautic.request(db, "GET", "/api/contacts?limit=1")
    segments = mautic.request(db, "GET", "/api/segments?limit=100")
    contact_total = mautic.contact_total(contacts.payload) if contacts.ok else None
    segment_list = mautic.segment_rows(segments.payload) if segments.ok else None
    if not contacts.ok and not segments.ok:
        detail = contacts.detail or segments.detail
        return {"ok": False, "contacts": None, "segments": None, "detail": detail}
    parts = []
    if contacts.ok:
        parts.append("Mautic returned the contact total." if contact_total is not None else "Mautic answered, without a contact total.")
    else:
        parts.append(f"Contacts were not returned. {contacts.detail}")
    if segments.ok and segment_list is not None:
        parts.append("Mautic returned the segment list.")
    elif segments.ok:
        parts.append("Mautic answered, without a segment list.")
    else:
        parts.append(f"Segments were not returned. {segments.detail}")
    return {
        "ok": True,
        "contacts": contact_total,
        "segments": segment_list,
        "detail": " ".join(parts),
    }


def save_assistant_draft(db: Session, purpose: str, text: str) -> dict:
    body = text.strip()
    if not body:
        raise HTTPException(status_code=400, detail="There is no draft to save.")
    if purpose == "campaign":
        saved = create_campaign(db, {"name": "Assistant draft", "subject": "Survey Café", "body": body})
        return {"published": False, "kind": "campaign", "record": saved}
    if purpose in {"social", "event", "ideas", "review"}:
        row = SocialPost(
            body=body,
            channels_json="[]",
            media_json="[]",
            status="draft",
            detail="Saved from the assistant. It has not been sent to Postiz.",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(row)
        audit(db, "assistant.save", purpose)
        db.commit()
        db.refresh(row)
        return {"published": False, "kind": "post", "record": post_out(row)}
    raise HTTPException(status_code=400, detail="That draft cannot be saved.")


def customer_activity(db: Session) -> dict | None:
    result = mautic.request(db, "GET", "/api/contacts?limit=1")
    if not result.ok:
        return None
    total = mautic.contact_total(result.payload)
    if total is None:
        return None
    return {"source": "mautic", "contacts": total, "detail": "Contact total reported by Mautic."}


def overview(db: Session) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    posts = db.query(SocialPost).order_by(SocialPost.id.desc()).all()
    counts: dict[str, int] = {}
    for row in posts:
        counts[row.status] = counts.get(row.status, 0) + 1
    in_progress = [row for row in posts if row.status in {"draft", "submitted"}]
    scheduled = [row for row in posts if row.status in {"draft", "submitted"} and row.scheduled_for]
    published = [row for row in posts if row.status == "published"]
    failed = [row for row in posts if row.status == "error"]
    reviews = db.query(Review).order_by(Review.id.desc()).limit(6).all()
    events = db.query(Event).order_by(Event.starts_at.asc()).limit(6).all()
    campaigns = db.query(Campaign).order_by(Campaign.id.desc()).limit(6).all()
    notes = db.query(Notification).order_by(Notification.id.desc()).limit(8).all()
    latest_ads = ad_rows(db)
    statuses = service_status(db)
    mautic_row = next((row for row in statuses if row["service"] == "mautic"), {})
    return {
        "generated_at": now,
        "statuses": statuses,
        "customer_activity": customer_activity(db) if mautic_row.get("authenticated") else None,
        "counts": {
            "posts_in_progress": len(in_progress),
            "posts_scheduled": len(scheduled),
            "posts_published": len(published),
            "posts_failed": len(failed),
            "campaigns": db.query(Campaign).count(),
            "campaigns_draft": db.query(Campaign).filter(Campaign.status.in_(["local", "mautic_draft"])).count(),
            "reviews_pending": db.query(Review).filter(Review.approval == "pending").count(),
            "events": db.query(Event).count(),
            "notifications_unread": db.query(Notification).filter(Notification.read.is_(False)).count(),
        },
        "posts_by_status": [{"status": key, "count": value} for key, value in sorted(counts.items())],
        "posts": [post_out(row) for row in in_progress[:6]],
        "scheduled_posts": [post_out(row) for row in scheduled[:6]],
        "published_posts": [post_out(row) for row in published[:6]],
        "failed_posts": [post_out(row) for row in failed[:6]],
        "engagement": None,
        "campaigns": [campaign_out(row) for row in campaigns],
        "reviews": [review_out(row) for row in reviews],
        "events": [event_out(row) for row in events],
        "notifications": [
            {
                "id": row.id,
                "level": row.level,
                "title": row.title,
                "body": row.body,
                "read": row.read,
                "created_at": stamp(row.created_at),
            }
            for row in notes
        ],
        "ad_spend": [
            {
                "platform": platform,
                "spend_cents": sum(row["spend_cents"] for row in latest_ads if row["platform"] == platform),
            }
            for platform in sorted({row["platform"] for row in latest_ads})
        ],
    }


def mark_notification(db: Session, note_id: int) -> dict:
    row = db.get(Notification, note_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read = True
    db.commit()
    return {"id": row.id, "read": True}


def settings_view(db: Session) -> dict:
    fields = []
    for field in SECRET_FIELDS:
        value = get_secret(db, field["name"])
        fields.append(
            {
                **field,
                "configured": bool(value),
                "value": value if field["name"] in PUBLIC_SECRETS and value else "",
            }
        )
    return {"fields": fields}


def save_secret(db: Session, name: str, value: str) -> dict:
    if not settings.command_secret_key:
        raise HTTPException(status_code=503, detail="COMMAND_SECRET_KEY is not set, so credentials cannot be stored.")
    try:
        set_secret(db, name, value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown setting") from exc
    audit(db, "secret.save" if value.strip() else "secret.clear", name)
    db.commit()
    return settings_view(db)


def system_view() -> dict:
    driver = "postgres" if settings.database_url.startswith("postgres") else "sqlite"
    return {
        "data_dir": settings.data_dir,
        "database": driver,
        "https_only": settings.command_https_only,
        "public_url": settings.command_public_url,
        "ollama": bool(settings.ollama_base_url and settings.ollama_text_model),
        "vision": bool(settings.ollama_base_url and settings.ollama_vision_model),
        "version": "0.1.0",
    }


def export_bundle(db: Session) -> dict:
    return {
        "profiles": [profile_out(row) for row in db.query(BusinessProfile).all()],
        "menu_items": [item_out(row) for row in db.query(MenuItem).all()],
        "posts": [post_out(row) for row in db.query(SocialPost).all()],
        "campaigns": [campaign_out(row) for row in db.query(Campaign).all()],
        "reviews": [review_out(row) for row in db.query(Review).all()],
        "events": [event_out(row) for row in db.query(Event).all()],
        "secrets_included": False,
    }


def integration_summary(db: Session) -> dict:
    return {
        "mautic_configured": configured(db, "mautic_username") and configured(db, "mautic_password"),
        "postiz_configured": configured(db, "postiz_api_key"),
        "google_configured": configured(db, "google_access_token") and configured(db, "google_location_id"),
        "google_ads_configured": configured(db, "google_ads_developer_token"),
        "meta_ads_configured": configured(db, "meta_access_token"),
        "yelp_configured": configured(db, "yelp_api_key"),
    }
