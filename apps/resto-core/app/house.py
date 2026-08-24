"""Kitchen house board: fridge temps and camera tiles."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Camera, Fridge, FridgeReading

STALE_MINUTES = 30
DEAD_MINUTES = 120

DEFAULT_FRIDGES = (
    {"slug": "walk-in-cooler", "name": "Walk-in cooler", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 10},
    {"slug": "prep-cooler", "name": "Prep fridge", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 20},
    {"slug": "pastry-cooler", "name": "Dessert fridge", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 40},
    {"slug": "bar-cooler", "name": "Soda fridge", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 50},
    {"slug": "salad-fridge", "name": "Salad fridge", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 55},
    {"slug": "coffee-station", "name": "Coffee station", "kind": "cooler", "min_temp_f": 34, "max_temp_f": 40, "sort": 58},
    {"slug": "walk-in-freezer", "name": "Walk-in freezer", "kind": "freezer", "min_temp_f": -10, "max_temp_f": 10, "sort": 70},
)

# YoLink entity names Paul already set in the app.
FRIDGE_ALIASES = {
    "walkin-cooler": "walk-in-cooler",
    "prep-fridge": "prep-cooler",
    "dessert-fridge": "pastry-cooler",
    "soda-fridge": "bar-cooler",
}

DEFAULT_CAMERAS = (
    {"slug": "front-door", "name": "Front door", "kind": "door", "sort": 10},
    {"slug": "kitchen", "name": "Kitchen", "kind": "kitchen", "sort": 20},
    {"slug": "line", "name": "Line", "kind": "line", "sort": 30},
    {"slug": "parking", "name": "Parking", "kind": "parking", "sort": 40},
)

# Kitchen is the live Frigate camera today. Point every cooler at it until the others have RTSP.
FRIDGE_CAMERA = {
    "walk-in-cooler": "kitchen",
    "prep-cooler": "kitchen",
    "pastry-cooler": "kitchen",
    "bar-cooler": "kitchen",
    "salad-fridge": "kitchen",
    "coffee-station": "kitchen",
    "walk-in-freezer": "kitchen",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:80] or "fridge"


def to_fahrenheit(temp_f=None, temp_c=None) -> Decimal | None:
    if temp_f not in (None, ""):
        return Decimal(str(temp_f)).quantize(Decimal("0.1"))
    if temp_c not in (None, ""):
        celsius = Decimal(str(temp_c))
        return ((celsius * Decimal("9") / Decimal("5")) + Decimal("32")).quantize(Decimal("0.1"))
    return None


def safe_http_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("/frigate/") or lowered.startswith("https://") or lowered.startswith("http://"):
        return text[:400]
    return ""


def frigate_snapshot_url(slug: str) -> str:
    return f"/frigate/api/{slugify(slug)}/latest.jpg"


def frigate_stream_url(slug: str) -> str:
    return f"{settings.frigate_public_url.rstrip('/')}/#{slugify(slug)}"


def _managed_camera_url(url: str) -> bool:
    text = str(url or "")
    return (not text) or "/frigate/api/" in text or ":8971" in text or text.endswith("latest.jpg")


def apply_frigate_camera_urls(db: Session) -> None:
    """Point cellar cameras at Frigate's per-camera snapshot, proxied on this host."""
    for spec in DEFAULT_CAMERAS:
        row = db.query(Camera).filter(Camera.slug == spec["slug"]).first()
        if row is None:
            continue
        if _managed_camera_url(row.snapshot_url):
            row.snapshot_url = frigate_snapshot_url(spec["slug"])
        if _managed_camera_url(row.stream_url):
            row.stream_url = frigate_stream_url(spec["slug"])
    db.commit()


def camera_for_fridge(db: Session, fridge: Fridge | None) -> Camera | None:
    slug = FRIDGE_CAMERA.get(fridge.slug if fridge else "", "kitchen")
    return db.query(Camera).filter(Camera.slug == slug, Camera.is_active.is_(True)).first()


def find_fridge(db: Session, name: str = "", slug: str = "") -> Fridge | None:
    key = slugify(slug or "")
    if key in FRIDGE_ALIASES:
        key = FRIDGE_ALIASES[key]
    if key:
        row = db.query(Fridge).filter(Fridge.slug == key, Fridge.is_active.is_(True)).first()
        if row:
            return row
    label = str(name or slug or "").strip()
    if not label:
        return None
    row = db.query(Fridge).filter(Fridge.name.ilike(label), Fridge.is_active.is_(True)).first()
    if row:
        return row
    key = slugify(label)
    if key in FRIDGE_ALIASES:
        key = FRIDGE_ALIASES[key]
    row = db.query(Fridge).filter(Fridge.slug == key, Fridge.is_active.is_(True)).first()
    if row:
        return row
    return db.query(Fridge).filter(Fridge.is_active.is_(True), Fridge.slug.ilike(f"%{key}%") | Fridge.name.ilike(f"%{label}%")).first()


def ensure_house(db: Session) -> None:
    for spec in DEFAULT_FRIDGES:
        row = db.query(Fridge).filter(Fridge.slug == spec["slug"]).first()
        if row is None:
            row = Fridge(slug=spec["slug"])
            db.add(row)
        row.name = spec["name"]
        row.kind = spec["kind"]
        row.min_temp_f = Decimal(str(spec["min_temp_f"]))
        row.max_temp_f = Decimal(str(spec["max_temp_f"]))
        row.sort = spec["sort"]
        row.is_active = True
    keep = {spec["slug"] for spec in DEFAULT_FRIDGES}
    for row in db.query(Fridge).all():
        row.is_active = row.slug in keep
    for spec in DEFAULT_CAMERAS:
        row = db.query(Camera).filter(Camera.slug == spec["slug"]).first()
        if row is None:
            db.add(
                Camera(
                    slug=spec["slug"],
                    name=spec["name"],
                    kind=spec["kind"],
                    sort=spec["sort"],
                    is_active=True,
                )
            )
    db.commit()
    apply_frigate_camera_urls(db)


def record_reading(
    db: Session,
    fridge: Fridge,
    temp_f: Decimal,
    humidity=None,
    source: str = "manual",
    recorded_at: datetime | None = None,
) -> FridgeReading:
    humidity_val = None if humidity in (None, "") else Decimal(str(humidity)).quantize(Decimal("0.1"))
    row = FridgeReading(
        fridge_id=fridge.id,
        recorded_at=recorded_at or _now(),
        temp_f=Decimal(str(temp_f)).quantize(Decimal("0.1")),
        humidity=humidity_val,
        source=str(source or "manual")[:40],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reading_status(fridge: Fridge, reading: FridgeReading | None, now: datetime | None = None) -> str:
    if reading is None:
        return "empty"
    age = (now or _now()) - reading.recorded_at
    if age > timedelta(minutes=DEAD_MINUTES):
        return "stale"
    temp = Decimal(str(reading.temp_f))
    if temp < Decimal(str(fridge.min_temp_f)) or temp > Decimal(str(fridge.max_temp_f)):
        return "alert"
    if age > timedelta(minutes=STALE_MINUTES):
        return "warn"
    return "ok"


def age_label(recorded_at: datetime | None, now: datetime | None = None) -> str:
    if recorded_at is None:
        return "No reading yet"
    minutes = int(((now or _now()) - recorded_at).total_seconds() // 60)
    if minutes < 1:
        return "Just now"
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours == 1:
        return "1 hour ago"
    if hours < 36:
        return f"{hours} hours ago"
    return recorded_at.strftime("%b %d %I:%M %p").lstrip("0").replace(" 0", " ")


def house_board(db: Session) -> dict:
    ensure_house(db)
    now = _now()
    fridges = []
    alerts = 0
    online = 0
    for fridge in db.query(Fridge).filter(Fridge.is_active.is_(True)).order_by(Fridge.sort, Fridge.name):
        reading = (
            db.query(FridgeReading)
            .filter(FridgeReading.fridge_id == fridge.id)
            .order_by(FridgeReading.recorded_at.desc(), FridgeReading.id.desc())
            .first()
        )
        status = reading_status(fridge, reading, now)
        if status == "alert":
            alerts += 1
        if status in ("ok", "warn", "alert"):
            online += 1
        history = (
            db.query(FridgeReading)
            .filter(FridgeReading.fridge_id == fridge.id)
            .order_by(FridgeReading.recorded_at.desc())
            .limit(8)
            .all()
        )
        fridges.append(
            {
                "fridge": fridge,
                "reading": reading,
                "temp_f": Decimal(str(reading.temp_f)) if reading else None,
                "humidity": Decimal(str(reading.humidity)) if reading and reading.humidity is not None else None,
                "status": status,
                "age": age_label(reading.recorded_at if reading else None, now),
                "history": list(reversed(history)),
            }
        )
    cameras = db.query(Camera).filter(Camera.is_active.is_(True)).order_by(Camera.sort, Camera.name).all()
    return {
        "fridges": fridges,
        "cameras": cameras,
        "alerts": alerts,
        "online": online,
        "total": len(fridges),
        "live_cameras": sum(1 for cam in cameras if cam.snapshot_url or cam.stream_url),
    }


def house_series(db: Session, start: datetime, end: datetime, live_cameras: int = 0) -> dict:
    """Daily average fridge temp and cameras live — two dashboard lines."""
    cursor = start.date()
    last = end.date()
    labels: list[str] = []
    days: list = []
    while cursor <= last:
        labels.append(cursor.isoformat())
        days.append(cursor)
        cursor += timedelta(days=1)
    buckets: dict[str, list[float]] = {key: [] for key in labels}
    readings = (
        db.query(FridgeReading)
        .filter(FridgeReading.recorded_at >= start, FridgeReading.recorded_at <= end)
        .all()
    )
    for row in readings:
        if not row.recorded_at:
            continue
        key = row.recorded_at.date().isoformat()
        if key in buckets:
            buckets[key].append(float(row.temp_f))
    temperature = [round(sum(vals) / len(vals), 1) if vals else None for key, vals in ((label, buckets[label]) for label in labels)]
    cameras = [None for _ in labels]
    if labels:
        cameras[-1] = int(live_cameras or 0)
    return {"labels": labels, "temperature": temperature, "cameras": cameras}


def fridge_chart(db: Session, fridge: Fridge, hours: int = 24) -> dict:
    """Point-by-point °F for one fridge, plus the swing in that window."""
    window = 168 if int(hours or 24) >= 48 else 24
    now = _now()
    start = now - timedelta(hours=window)
    rows = (
        db.query(FridgeReading)
        .filter(
            FridgeReading.fridge_id == fridge.id,
            FridgeReading.recorded_at >= start,
            FridgeReading.recorded_at <= now,
        )
        .order_by(FridgeReading.recorded_at, FridgeReading.id)
        .all()
    )
    temps = [float(row.temp_f) for row in rows]
    labels = [row.recorded_at.replace(microsecond=0).isoformat() + "Z" for row in rows]
    low = min(temps) if temps else None
    high = max(temps) if temps else None
    min_ok = float(fridge.min_temp_f)
    max_ok = float(fridge.max_temp_f)
    return {
        "labels": labels,
        "temperature": temps,
        "min_ok": [min_ok for _ in labels],
        "max_ok": [max_ok for _ in labels],
        "low": low,
        "high": high,
        "swing": round(high - low, 1) if temps else None,
        "latest": temps[-1] if temps else None,
        "hours": window,
        "count": len(rows),
        "out_of_range": sum(1 for temp in temps if temp < min_ok or temp > max_ok),
        "min_temp_f": min_ok,
        "max_temp_f": max_ok,
    }


def house_payload(board: dict) -> dict:
    fridges = []
    for card in board["fridges"]:
        fridge = card["fridge"]
        reading = card["reading"]
        fridges.append(
            {
                "slug": fridge.slug,
                "name": fridge.name,
                "kind": fridge.kind,
                "min_temp_f": float(fridge.min_temp_f),
                "max_temp_f": float(fridge.max_temp_f),
                "temp_f": float(card["temp_f"]) if card["temp_f"] is not None else None,
                "humidity": float(card["humidity"]) if card["humidity"] is not None else None,
                "status": card["status"],
                "age": card["age"],
                "recorded_at": reading.recorded_at.isoformat() if reading else None,
                "source": reading.source if reading else "",
            }
        )
    return {
        "alerts": board["alerts"],
        "online": board["online"],
        "total": board["total"],
        "fridges": fridges,
        "cameras": [
            {"slug": cam.slug, "name": cam.name, "kind": cam.kind, "has_feed": bool(cam.snapshot_url or cam.stream_url)}
            for cam in board["cameras"]
        ],
    }
