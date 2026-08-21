import httpx
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.catalog import catalog_lexicon, scan_catalogs
from app.config import settings
from app.connections import access_token_for
from app.costing import money
from app.db import get_db
from app.matching import match_sellables
from app.models import Connector, Invoice, Product, Recipe, SellableItem, StockMove, WineProfile
from app.purchasing import CATEGORIES, purchasing_board
from app.services import catalog_counts, period_costing, sales_span, wine_rows

router = APIRouter()
ALLOWED_DAYS = (7, 30, 90, 365)
DEFAULT_DAYS = 90
INVOICE_PAGE_SIZE = 40
SCAN_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def render(request: Request, template: str, **context):
    return request.app.state.templates.TemplateResponse(request, template, context)


def _flash(request: Request, ok: str = "", err: str = "") -> None:
    if ok:
        request.session["flash_ok"] = ok
    if err:
        request.session["flash_err"] = err


def _pop_flash(request: Request) -> tuple[str, str]:
    return request.session.pop("flash_ok", ""), request.session.pop("flash_err", "")


def _period(days: int | None = None) -> tuple[int, datetime, datetime]:
    window = days if days in ALLOWED_DAYS else DEFAULT_DAYS
    end = datetime.now(UTC).replace(tzinfo=None)
    return window, end - timedelta(days=window), end


@router.get("/")
def dashboard(request: Request, days: int = DEFAULT_DAYS, db: Session = Depends(get_db)):
    window, start, end = _period(days)
    costing = period_costing(db, start, end)
    wines = wine_rows(db)
    cellar_value = money(sum((row["cellar_value"] for row in wines), Decimal(0)))
    below_par = [row for row in wines if row["below_par"]]
    connectors = db.query(Connector).order_by(Connector.name).all()
    invoices = db.query(Invoice).order_by(Invoice.issued_on.desc()).limit(6).all()
    purchasing = purchasing_board(db)
    return render(
        request,
        "dashboard.html",
        costing=costing,
        wines=wines,
        cellar_value=cellar_value,
        below_par=below_par,
        connectors=connectors,
        invoices=invoices,
        purchasing=purchasing,
        days=window,
        span=sales_span(db),
        counts=catalog_counts(db),
        page="dashboard",
    )


@router.get("/wines")
def wines_list(request: Request, db: Session = Depends(get_db)):
    return render(request, "wines.html", wines=wine_rows(db), page="wines")


@router.get("/wines/new")
def wine_new(request: Request):
    return render(request, "wine_form.html", wine=None, page="wines")


@router.get("/wines/{product_id}")
def wine_detail(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product or not product.wine:
        return RedirectResponse("/wines", status_code=303)
    row = next((item for item in wine_rows(db) if item["product"].id == product_id), None)
    moves = (
        db.query(StockMove)
        .filter(StockMove.product_id == product_id)
        .order_by(StockMove.occurred_at.desc())
        .limit(30)
        .all()
    )
    return render(request, "wine_detail.html", row=row, moves=moves, page="wines")


@router.get("/wines/{product_id}/edit")
def wine_edit(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product or not product.wine:
        return RedirectResponse("/wines", status_code=303)
    row = next((item for item in wine_rows(db) if item["product"].id == product_id), None)
    return render(request, "wine_form.html", wine=row, page="wines")


def _upsert_wine(
    db: Session,
    product: Product | None,
    name: str,
    producer: str,
    vintage: str,
    color: str,
    country: str,
    region: str,
    appellation: str,
    grape: str,
    bin_location: str,
    bottle_size_ml: int,
    glass_pour_ml: int,
    par_bottles: str,
    bottle_cost: str,
    glass_price: str,
    bottle_price: str,
    list_type: str,
) -> Product:
    sku_base = f"{name}-{vintage}-{producer}".upper().replace(" ", "-")[:70]
    bottle_cost_d = Decimal(bottle_cost or "0")
    if product is None:
        sku = sku_base
        exists = db.query(Product).filter(Product.sku == sku).count()
        if exists:
            sku = f"{sku_base}-{int(datetime.now(UTC).timestamp())}"
        product = Product(sku=sku, name=name.strip(), category="wine", base_unit="ml")
        db.add(product)
        db.flush()
        db.add(WineProfile(product_id=product.id))
        db.flush()
    product.name = name.strip()
    product.current_cost = (bottle_cost_d / Decimal(bottle_size_ml)) if bottle_size_ml else Decimal(0)
    profile = product.wine
    profile.producer = producer
    profile.vintage = vintage
    profile.color = color
    profile.country = country
    profile.region = region
    profile.appellation = appellation
    profile.grape = grape
    profile.bin_location = bin_location
    profile.bottle_size_ml = bottle_size_ml
    profile.glass_pour_ml = glass_pour_ml
    profile.par_bottles = Decimal(par_bottles or "0")
    profile.list_type = list_type

    def upsert_sellable(label: str, qty: int, price: str) -> None:
        item = next((s for s in product.sellables if s.name.endswith(label)), None)
        if item is None:
            item = SellableItem(product_id=product.id, name=f"{name} {label}", costing_group="wine")
            db.add(item)
        item.name = f"{name} {label}"
        item.serving_qty = qty
        item.serving_unit = "ml"
        item.selling_price = Decimal(price or "0")
        item.is_active = Decimal(price or "0") > 0

    upsert_sellable("glass", glass_pour_ml, glass_price)
    upsert_sellable("bottle", bottle_size_ml, bottle_price)
    db.commit()
    return product


@router.post("/wines/new")
def wine_create(
    name: str = Form(...),
    producer: str = Form(""),
    vintage: str = Form(""),
    color: str = Form("red"),
    country: str = Form(""),
    region: str = Form(""),
    appellation: str = Form(""),
    grape: str = Form(""),
    bin_location: str = Form(""),
    bottle_size_ml: int = Form(750),
    glass_pour_ml: int = Form(150),
    par_bottles: str = Form("0"),
    bottle_cost: str = Form("0"),
    glass_price: str = Form("0"),
    bottle_price: str = Form("0"),
    list_type: str = Form("both"),
    db: Session = Depends(get_db),
):
    product = _upsert_wine(
        db, None, name, producer, vintage, color, country, region, appellation, grape, bin_location,
        bottle_size_ml, glass_pour_ml, par_bottles, bottle_cost, glass_price, bottle_price, list_type,
    )
    return RedirectResponse(f"/wines/{product.id}", status_code=303)


@router.post("/wines/{product_id}/edit")
def wine_update(
    product_id: int,
    name: str = Form(...),
    producer: str = Form(""),
    vintage: str = Form(""),
    color: str = Form("red"),
    country: str = Form(""),
    region: str = Form(""),
    appellation: str = Form(""),
    grape: str = Form(""),
    bin_location: str = Form(""),
    bottle_size_ml: int = Form(750),
    glass_pour_ml: int = Form(150),
    par_bottles: str = Form("0"),
    bottle_cost: str = Form("0"),
    glass_price: str = Form("0"),
    bottle_price: str = Form("0"),
    list_type: str = Form("both"),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        return RedirectResponse("/wines", status_code=303)
    _upsert_wine(
        db, product, name, producer, vintage, color, country, region, appellation, grape, bin_location,
        bottle_size_ml, glass_pour_ml, par_bottles, bottle_cost, glass_price, bottle_price, list_type,
    )
    return RedirectResponse(f"/wines/{product_id}", status_code=303)


@router.post("/wines/{product_id}/receive")
def wine_receive(
    product_id: int,
    bottles: str = Form(...),
    unit_cost: str = Form("0"),
    location: str = Form("cellar"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product or not product.wine:
        return RedirectResponse("/wines", status_code=303)
    qty_bottles = Decimal(bottles)
    cost = Decimal(unit_cost or "0")
    db.add(
        StockMove(
            product_id=product.id,
            qty_base=qty_bottles * Decimal(product.wine.bottle_size_ml),
            unit_cost=cost,
            reason="receive",
            location=location,
            notes=notes,
        )
    )
    if cost > 0:
        product.current_cost = cost / Decimal(product.wine.bottle_size_ml)
    db.commit()
    return RedirectResponse(f"/wines/{product_id}", status_code=303)


@router.get("/inventory")
def inventory(request: Request, db: Session = Depends(get_db)):
    return render(request, "inventory.html", wines=wine_rows(db), page="inventory")


@router.post("/inventory/count")
async def inventory_count(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    location = str(form.get("location") or "cellar")
    notes = str(form.get("notes") or "Physical count")
    from app.models import InventoryCount, InventoryCountLine

    count = InventoryCount(location=location, notes=notes)
    db.add(count)
    db.flush()
    for row in wine_rows(db):
        product = row["product"]
        field = f"count_{product.id}"
        if field not in form:
            continue
        counted_bottles = Decimal(str(form.get(field) or "0"))
        counted_ml = counted_bottles * Decimal(row["profile"].bottle_size_ml)
        expected = row["on_hand_ml"]
        db.add(
            InventoryCountLine(
                count_id=count.id,
                product_id=product.id,
                counted_qty_base=counted_ml,
                expected_qty_base=expected,
            )
        )
        delta = counted_ml - expected
        if delta != 0:
            db.add(
                StockMove(
                    product_id=product.id,
                    qty_base=delta,
                    unit_cost=row["bottle_cost"],
                    reason="count_adjust",
                    location=location,
                    notes=f"Count variance {delta} ml",
                )
            )
    db.commit()
    return RedirectResponse("/inventory", status_code=303)


@router.get("/costing")
def costing_page(request: Request, days: int = DEFAULT_DAYS, db: Session = Depends(get_db)):
    window, start, end = _period(days)
    costing = period_costing(db, start, end)
    wines = wine_rows(db)
    counts = catalog_counts(db)
    return render(
        request,
        "costing.html",
        costing=costing,
        wines=wines,
        days=window,
        counts=counts,
        page="costing",
    )


@router.get("/costing/match")
def costing_match(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    unmatched = (
        db.query(SellableItem)
        .filter(SellableItem.recipe_id.is_(None), SellableItem.product_id.is_(None))
        .order_by(SellableItem.name)
        .limit(80)
        .all()
    )
    recipes = db.query(Recipe).order_by(Recipe.name).limit(80).all()
    return render(
        request,
        "costing_match.html",
        unmatched=unmatched,
        recipes=recipes,
        counts=catalog_counts(db),
        flash_ok=ok,
        flash_err=err,
        page="costing",
    )


@router.post("/costing/match")
def costing_match_run(request: Request, db: Session = Depends(get_db)):
    result = match_sellables(db)
    _flash(
        request,
        ok=f"Linked {result.get('recipes', 0)} Square items to recipes and {result.get('wines', 0)} to wines.",
    )
    return RedirectResponse("/costing/match", status_code=303)


@router.get("/invoices")
def invoices_page(request: Request, p: int = 1, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    total_count = db.query(Invoice).count()
    pages = max(1, (total_count + INVOICE_PAGE_SIZE - 1) // INVOICE_PAGE_SIZE)
    page_number = min(max(p, 1), pages)
    invoices = (
        db.query(Invoice)
        .options(joinedload(Invoice.supplier), joinedload(Invoice.lines))
        .order_by(Invoice.issued_on.desc(), Invoice.id.desc())
        .offset((page_number - 1) * INVOICE_PAGE_SIZE)
        .limit(INVOICE_PAGE_SIZE)
        .all()
    )
    filed_total = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0))) or 0
    return render(
        request,
        "invoices.html",
        invoices=invoices,
        page_number=page_number,
        pages=pages,
        total_count=total_count,
        filed_total=filed_total,
        counts=catalog_counts(db),
        flash_ok=ok,
        flash_err=err,
        page="invoices",
    )


@router.get("/invoices/scan")
def invoices_scan(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    connected = bool(access_token_for(db, "paperless"))
    paperless_url = settings.paperless_public_url or settings.paperless_base_url
    return render(
        request,
        "invoice_scan.html",
        flash_ok=ok,
        flash_err=err,
        paperless_connected=connected,
        paperless_url=paperless_url,
        page="scan",
    )


def _scan_uploads(camera: UploadFile | None, files: list[UploadFile] | None) -> list[UploadFile]:
    uploads: list[UploadFile] = []
    if camera and camera.filename:
        uploads.append(camera)
    for item in files or []:
        if item and item.filename:
            uploads.append(item)
    return uploads


@router.post("/invoices/scan")
async def invoices_scan_upload(
    request: Request,
    vendor: str = Form(""),
    camera: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
):
    token = access_token_for(db, "paperless")
    if not token:
        _flash(request, err="Connect Paperless first, then come back and take the photos.")
        return RedirectResponse("/connect", status_code=303)
    uploads = _scan_uploads(camera, files)
    if not uploads:
        _flash(request, err="Take a photo or pick files from Photos first.")
        return RedirectResponse("/invoices/scan", status_code=303)
    base = settings.paperless_base_url.rstrip("/")
    headers = {"Authorization": f"Token {token}"}
    sent = 0
    errors = []
    vendor_name = vendor.strip()
    try:
        with httpx.Client(timeout=SCAN_TIMEOUT) as client:
            for upload in uploads:
                content = await upload.read()
                if not content:
                    continue
                filename = upload.filename or "invoice.jpg"
                content_type = upload.content_type or "image/jpeg"
                title = vendor_name or filename.rsplit(".", 1)[0]
                response = client.post(
                    f"{base}/api/documents/post_document/",
                    headers=headers,
                    files={"document": (filename, content, content_type)},
                    data={"title": title[:240]},
                )
                if response.status_code >= 400:
                    errors.append(filename)
                    continue
                sent += 1
    except Exception:  # noqa: BLE001
        _flash(request, err="Could not reach Paperless. Check Connect, then try again.")
        return RedirectResponse("/invoices/scan", status_code=303)
    if sent and not errors:
        _flash(request, ok=f"Sent {sent} photo(s) to Paperless. Shoot the next pile — costing will catch them.")
    elif sent:
        _flash(request, ok=f"Sent {sent}. Could not send {len(errors)}.", err="Some photos did not upload.")
    else:
        _flash(request, err="Paperless did not take those photos. Try JPEG or PDF.")
    return RedirectResponse("/invoices/scan", status_code=303)


@router.get("/connectors")
def connectors_page(request: Request, db: Session = Depends(get_db)):
    connectors = db.query(Connector).order_by(Connector.kind, Connector.name).all()
    return render(request, "connectors.html", connectors=connectors, page="connectors")


@router.post("/connectors/{connector_id}/status")
def connector_status(connector_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    connector = db.get(Connector, connector_id)
    if connector:
        connector.status = status
        db.commit()
    return RedirectResponse("/connectors", status_code=303)


@router.get("/purchasing")
def purchasing_page(request: Request, category: str = "", db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    chosen = category if category in CATEGORIES else ""
    board = purchasing_board(db, chosen)
    return render(
        request,
        "purchasing.html",
        board=board,
        categories=CATEGORIES,
        catalogs=catalog_lexicon(),
        flash_ok=ok,
        flash_err=err,
        page="purchasing",
    )


@router.post("/purchasing/scan")
def purchasing_scan(request: Request, db: Session = Depends(get_db)):
    try:
        result = scan_catalogs(db)
        quotes = int(result.get("quotes") or 0)
        _flash(request, ok=f"Public catalog scan finished. {quotes} listed pack(s) recorded today.")
    except Exception:  # noqa: BLE001
        _flash(request, err="Catalog scan failed. Public sites block bots more often than they list prices.")
    return RedirectResponse("/purchasing", status_code=303)

