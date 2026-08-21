from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.ingest import ingest_paperless_doc, ingest_recipes, ingest_sales
from app.paperless_hook import ensure_paperless_sync_workflow, sync_paperless_now
from app.purchasing import COMPARE_DAYS, DEFAULT_COMPARE_DAYS, board_payload, purchasing_board
from app.catalog import scan_catalogs
from app.collector import ingest_collected_items
from app.equivalents import watch_payload, COLLECTOR_PRODUCT_CAP
from app.intel import overnight_report, save_collector_run, set_browser_status
from app.market import scan_external_prices
from app.services import period_costing, wine_rows
from app.sync import sync_all, sync_paperless

router = APIRouter(prefix="/api")


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not x_api_key or x_api_key != settings.resto_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class SaleIn(BaseModel):
    sold_at: datetime
    name: str
    qty: Decimal = 1
    unit_price: Decimal = 0
    revenue: Decimal | None = None
    square_order_id: str = ""
    square_line_id: str = ""
    square_item_id: str = ""
    costing_group: str = "food"


class SalesBatch(BaseModel):
    sales: list[SaleIn]


class PaperlessDocument(BaseModel):
    id: str | int
    title: str = ""
    correspondent: str | None = None
    created: str | None = None
    invoice_number: str = ""
    total: Decimal = Decimal(0)
    invoice_type: str = "food"
    content: str = ""
    lines: list[dict] = Field(default_factory=list)


@router.get("/health")
def api_health():
    return {"ok": True}


@router.get("/costing/summary", dependencies=[Depends(require_key)])
def costing_summary(days: int = 90, db: Session = Depends(get_db)):
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=days)
    return period_costing(db, start, end)


@router.get("/wines", dependencies=[Depends(require_key)])
def wines_json(db: Session = Depends(get_db)):
    rows = []
    for row in wine_rows(db):
        rows.append(
            {
                "id": row["product"].id,
                "sku": row["product"].sku,
                "name": row["product"].name,
                "producer": row["profile"].producer,
                "vintage": row["profile"].vintage,
                "color": row["profile"].color,
                "bin": row["profile"].bin_location,
                "on_hand_bottles": float(row["on_hand_bottles"]),
                "par_bottles": float(row["profile"].par_bottles or 0),
                "bottle_cost": float(row["bottle_cost"]),
                "glass_cost": float(row["glass_cost"]),
                "glass_price": float(row["glass_price"]),
                "bottle_price": float(row["bottle_price"]),
                "glass_cost_pct": float(row["glass_cost_pct"]),
                "cellar_value": float(row["cellar_value"]),
            }
        )
    return {"wines": rows}


@router.get("/purchasing", dependencies=[Depends(require_key)])
def purchasing_json(category: str = "", days: int = DEFAULT_COMPARE_DAYS, db: Session = Depends(get_db)):
    window = days if days in COMPARE_DAYS else DEFAULT_COMPARE_DAYS
    return board_payload(purchasing_board(db, category, days=window))


@router.post("/sales/import", dependencies=[Depends(require_key)])
def import_sales(batch: SalesBatch, db: Session = Depends(get_db)):
    return ingest_sales(db, [item.model_dump() for item in batch.sales])


@router.post("/webhooks/paperless", dependencies=[Depends(require_key)])
def paperless_webhook(doc: PaperlessDocument, db: Session = Depends(get_db)):
    return ingest_paperless_doc(db, doc.model_dump())


class RecipesBatch(BaseModel):
    recipes: list[dict]


@router.post("/recipes/import", dependencies=[Depends(require_key)])
def import_recipes(batch: RecipesBatch, db: Session = Depends(get_db)):
    return ingest_recipes(db, batch.recipes)


@router.post("/jobs/sync-all", dependencies=[Depends(require_key)])
def sync_all_job(db: Session = Depends(get_db)):
    return sync_all(db)


@router.post("/jobs/sync-paperless")
def sync_paperless_job(
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    token: str | None = None,
    recent: bool = True,
):
    offered = x_api_key or token
    if not offered or offered != settings.resto_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if recent:
        return sync_paperless_now(db, max_pages=3)
    return sync_paperless(db, max_pages=15)


class CollectItem(BaseModel):
    name: str
    pack: str = ""
    price: Decimal
    qty: Decimal | None = None
    unit: str = ""
    upc: str = ""
    sku: str = ""
    brand: str = ""
    url: str = ""
    discount: bool = False
    available: bool = True
    regular_price: Decimal | None = None
    promo_price: Decimal | None = None


class CollectBatch(BaseModel):
    supplier: str
    store: str = ""
    source: str = "extension"
    miles: Decimal = Decimal("0")
    captured_on: str = ""
    page_url: str = ""
    items: list[CollectItem] = Field(default_factory=list)


@router.get("/prices/ping", dependencies=[Depends(require_key)])
def prices_ping():
    return {"ok": True, "app": "cellar"}


@router.get("/prices/watch", dependencies=[Depends(require_key)])
def prices_watch(cap: int = 40, db: Session = Depends(get_db)):
    limit = cap if cap > 0 else 40
    if limit > COLLECTOR_PRODUCT_CAP:
        limit = COLLECTOR_PRODUCT_CAP
    return watch_payload(db, cap=limit)


@router.post("/prices/collect", dependencies=[Depends(require_key)])
def collect_prices(batch: CollectBatch, db: Session = Depends(get_db)):
    return ingest_collected_items(db, batch.model_dump())


class CollectorAuthIn(BaseModel):
    slug: str
    status: str
    error: str = ""


class CollectorRunIn(BaseModel):
    started_at: str = ""
    finished_at: str = ""
    checked: int = 0
    updated: int = 0
    unchanged: int = 0
    unavailable: int = 0
    needs_reauth: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)


@router.post("/collector/auth", dependencies=[Depends(require_key)])
def collector_auth(body: CollectorAuthIn, db: Session = Depends(get_db)):
    set_browser_status(db, body.slug, body.status, body.error)
    return {"ok": True, "slug": body.slug, "status": body.status}


@router.post("/collector/runs", dependencies=[Depends(require_key)])
def collector_runs(body: CollectorRunIn, db: Session = Depends(get_db)):
    run = save_collector_run(db, body.model_dump())
    return {"ok": True, "id": run.id}


@router.get("/collector/status", dependencies=[Depends(require_key)])
def collector_status(db: Session = Depends(get_db)):
    from app.intel import BROWSER_SOURCES, browser_status_for, latest_run

    sources = [browser_status_for(db, slug) | {"label": label} for slug, label in BROWSER_SOURCES]
    report = overnight_report(db)
    run = latest_run(db)
    return {
        "sources": sources,
        "needs_reauth": report["needs_reauth"],
        "last_run": {
            "checked": report["checked"],
            "updated": report["updated"],
            "unchanged": report["unchanged"],
            "unavailable": report["unavailable"],
            "finished_at": run.finished_at.isoformat() if run and run.finished_at else "",
        },
    }


@router.post("/jobs/scan-browser", dependencies=[Depends(require_key)])
def scan_browser_job():
    if not settings.collector_url:
        return {"ok": False, "status": "skipped", "reason": "collector_url is empty"}
    import httpx

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{settings.collector_url.rstrip('/')}/jobs/scan",
                headers={"X-API-Key": settings.resto_api_key},
            )
            return {"ok": response.is_success, "collector": response.json()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


@router.post("/jobs/scan-catalogs", dependencies=[Depends(require_key)])
def scan_catalogs_job(mode: str = "refresh", db: Session = Depends(get_db)):
    catalogs = scan_catalogs(db, mode=mode)
    external = scan_external_prices(db)
    return {"catalogs": catalogs, "external": external}


@router.post("/jobs/nightly", dependencies=[Depends(require_key)])
def nightly(db: Session = Depends(get_db)):
    synced = sync_all(db)
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=1)
    costing = period_costing(db, start, end)
    low_stock = [row["product"].name for row in wine_rows(db) if row["below_par"]]
    return {
        "ran_at": end.isoformat(),
        "sync": synced,
        "yesterday": costing["groups"],
        "wine_below_par": low_stock,
    }
