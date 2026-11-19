from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import domain
from app.capabilities import CAPABILITIES
from app.config import settings
from app.crypto import passwords_match
from app.db import get_db
from app.models import Audit, Campaign, Event, MenuDocument, MenuItem, Review, SocialPost

router = APIRouter(prefix="/api")
_failures: dict[str, list[float]] = defaultdict(list)


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    location_name: str = ""
    description: str = ""
    phone: str = ""
    website: str = ""
    hours: dict = {}
    holiday_hours: list = []
    announcement: str = ""


class PostIn(BaseModel):
    body: str = ""
    channels: list[dict] = []
    scheduled_for: str = ""


class CampaignIn(BaseModel):
    name: str
    subject: str = ""
    body: str = ""


class ReviewIn(BaseModel):
    platform: str
    author: str = ""
    rating: float = 0
    body: str
    reviewed_at: str = ""


class ApprovalIn(BaseModel):
    approval: str
    draft_response: str | None = None


class EventIn(BaseModel):
    name: str
    kind: str = "dinner"
    starts_at: str = ""
    ends_at: str = ""
    description: str = ""
    capacity: int | None = None


class EventPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    description: str | None = None
    capacity: int | None = None
    promo_text: str | None = None


class ItemPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    price_cents: int | None = None
    category: str | None = None
    approved: bool | None = None


class SecretIn(BaseModel):
    name: str
    value: str = ""


def require_user(request: Request) -> str:
    email = request.session.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in required")
    return email


def require_key(request: Request) -> None:
    expected = settings.command_api_key or settings.resto_api_key
    provided = request.headers.get("x-api-key", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="API key rejected")


def _locked(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _failures[ip] if now - stamp < 300]
    _failures[ip] = recent
    return len(recent) >= 5


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "local"
    if _locked(ip):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait a few minutes.")
    if not settings.command_admin_password or settings.command_admin_password.startswith("change-me"):
        raise HTTPException(status_code=503, detail="Set COMMAND_ADMIN_PASSWORD on the server before signing in.")
    email_ok = hmac.compare_digest(body.email.strip().lower(), settings.command_admin_email.strip().lower())
    password_ok = passwords_match(body.password, settings.command_admin_password)
    if not email_ok or not password_ok:
        _failures[ip].append(time.time())
        raise HTTPException(status_code=401, detail="Email or password is wrong")
    request.session["email"] = settings.command_admin_email
    return {"email": settings.command_admin_email}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    email = request.session.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in required")
    return {"email": email}


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.overview(db)


@router.get("/status")
def status(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return {"statuses": domain.service_status(db)}


@router.get("/capabilities")
def capabilities(_: str = Depends(require_user)):
    return {"capabilities": CAPABILITIES}


@router.get("/profiles")
def profiles(db: Session = Depends(get_db), _: str = Depends(require_user)):
    domain.ensure_profiles(db)
    rows = db.query(domain.BusinessProfile).all()
    return {"profiles": [domain.profile_out(row) for row in rows]}


@router.put("/profiles/{platform}")
def save_profile(platform: str, body: ProfileIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.save_profile(db, platform, body.model_dump())


@router.post("/profiles/{platform}/push")
def push_profile(platform: str, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.push_profile(db, platform)


@router.get("/menu/documents")
def menu_documents(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(MenuDocument).order_by(MenuDocument.id.desc()).all()
    return {"documents": [domain.document_out(row) for row in rows]}


@router.post("/menu/documents")
async def upload_menu(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
):
    blob = await file.read()
    return domain.add_menu_file(db, file.filename or "menu", file.content_type or "", blob)


@router.get("/menu/items")
def menu_items(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(MenuItem).order_by(MenuItem.id.asc()).all()
    return {"items": [domain.item_out(row) for row in rows]}


@router.patch("/menu/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.update_item(db, item_id, body.model_dump(exclude_unset=True))


@router.get("/posts")
def posts(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(SocialPost).order_by(SocialPost.id.desc()).all()
    return {"posts": [domain.post_out(row) for row in rows]}


@router.post("/posts")
def add_post(body: PostIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.create_post(db, body.model_dump())


@router.patch("/posts/{post_id}")
def patch_post(post_id: int, body: PostIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.update_post(db, post_id, body.model_dump())


@router.post("/posts/{post_id}/media")
async def post_media(
    post_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
):
    blob = await file.read()
    return domain.attach_media(db, post_id, file.filename or "media", file.content_type or "", blob)


@router.post("/posts/{post_id}/submit")
def submit_post(
    post_id: int,
    mode: str = "now",
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
):
    if mode not in {"now", "schedule"}:
        raise HTTPException(status_code=400, detail="Mode must be now or schedule")
    return domain.submit_post(db, post_id, mode)


@router.post("/posts/refresh")
def refresh_posts(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.refresh_posts(db)


@router.delete("/posts/{post_id}")
def remove_post(post_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.delete_post(db, post_id)


@router.get("/channels")
def channels(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.list_channels(db)


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(Campaign).order_by(Campaign.id.desc()).all()
    return {"campaigns": [domain.campaign_out(row) for row in rows]}


@router.post("/campaigns")
def add_campaign(body: CampaignIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.create_campaign(db, body.model_dump())


@router.post("/campaigns/pull")
def pull_campaigns(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.pull_campaigns(db)


@router.post("/campaigns/{campaign_id}/push")
def push_campaign(campaign_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.push_campaign(db, campaign_id)


@router.get("/ads")
def ads_view(db: Session = Depends(get_db), _: str = Depends(require_user)):
    latest = domain.ad_rows(db)
    from app.ads import recommendations

    return {"latest": latest, "recommendations": recommendations(latest)}


@router.post("/ads/sync")
def ads_sync(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.sync_ads(db)


@router.get("/reviews")
def reviews(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(Review).order_by(Review.id.desc()).all()
    return {"reviews": [domain.review_out(row) for row in rows]}


@router.post("/reviews")
def add_review(body: ReviewIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.add_review(db, body.model_dump())


@router.post("/reviews/pull")
def pull_reviews(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.pull_reviews(db)


@router.post("/reviews/{review_id}/draft")
def draft_review(review_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.draft_review(db, review_id)


@router.post("/reviews/{review_id}/approval")
def approve_review(review_id: int, body: ApprovalIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.set_review_approval(db, review_id, body.approval, body.draft_response)


@router.post("/reviews/{review_id}/send")
def send_review(review_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.send_review(db, review_id)


@router.get("/events")
def events(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(Event).order_by(Event.starts_at.asc()).all()
    return {"events": [domain.event_out(row) for row in rows]}


@router.post("/events")
def add_event(body: EventIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.create_event(db, body.model_dump())


@router.patch("/events/{event_id}")
def patch_event(event_id: int, body: EventPatch, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.update_event(db, event_id, body.model_dump(exclude_unset=True))


@router.post("/events/{event_id}/promo")
def promo_event(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.promo_event(db, event_id)


@router.post("/events/{event_id}/queue")
def queue_event(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.queue_event(db, event_id)


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.overview(db)["notifications"]


@router.post("/notifications/{note_id}/read")
def read_notification(note_id: int, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.mark_notification(db, note_id)


@router.get("/settings")
def settings_view(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return {**domain.settings_view(db), "system": domain.system_view(), "integrations": domain.integration_summary(db)}


@router.put("/settings/secrets")
def put_secret(body: SecretIn, db: Session = Depends(get_db), _: str = Depends(require_user)):
    return domain.save_secret(db, body.name, body.value)


@router.get("/audit")
def audit(db: Session = Depends(get_db), _: str = Depends(require_user)):
    rows = db.query(Audit).order_by(Audit.id.desc()).limit(30).all()
    return {
        "audit": [
            {"id": row.id, "action": row.action, "detail": row.detail, "created_at": row.created_at.isoformat()}
            for row in rows
        ]
    }


@router.get("/admin/export")
def export(db: Session = Depends(get_db), _: str = Depends(require_user)):
    return JSONResponse(domain.export_bundle(db))


@router.get("/n8n/status")
def n8n_status(db: Session = Depends(get_db), _: None = Depends(require_key)):
    return {"statuses": domain.service_status(db), "integrations": domain.integration_summary(db)}


@router.post("/n8n/events/announce")
def n8n_announce(body: EventIn, db: Session = Depends(get_db), _: None = Depends(require_key)):
    return domain.announce(db, body.model_dump())
