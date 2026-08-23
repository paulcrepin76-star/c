import json

import httpx
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.catalog import catalog_lexicon, scan_catalogs
from app.collector import collector_rows, playwright_available, source_label
from app.config import settings
from app.intel import BROWSER_SOURCES, PUBLIC_BROWSER_SLUGS, browser_status_for, overnight_report
from app.equivalents import connection_status, relevant_products, watch_payload
from app.geo import FAR_MILES, HOME_MARKET, NEAR_MILES
from app.market import scan_external_prices
from app.connections import access_token_for
from app.db import get_db
from app.ingest import INVOICE_TOTAL_MAX, PURCHASE_INVOICE_TYPES
from app.counts import COUNT_LOCATIONS, count_detail, count_sheet, recent_counts, save_count
from app.health import data_health
from app.matching import link_sellable, match_sellables, suggest_matches
from app.models import Connector, Invoice, Product, Recipe, SellableItem, StockMove, WineProfile
from app.drinks import DRINK_ORDER, drink_board, drink_spec, drinks_overview
from app.home import manager_home
from app.house import ensure_house, house_board, house_series, record_reading, safe_http_url, to_fahrenheit
from app.models import Camera, Fridge
from app.purchasing import CATEGORIES, COMPARE_DAYS, DEFAULT_COMPARE_DAYS, purchasing_board
from app.quickbooks import earliest_finance_date, finance_board, finance_period, finance_query, finance_view
from app.sales_report import sales_report, vendor_report
from app.services import catalog_counts, daily_activity, dashboard_charts, period_costing, wine_rows

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
    invoices = db.query(Invoice).order_by(Invoice.issued_on.desc()).limit(6).all()
    report = overnight_report(db)
    activity = daily_activity(db, start, end)
    house = house_board(db)
    series = house_series(db, start, end, live_cameras=house["live_cameras"])
    charts = dashboard_charts(costing, activity, series)
    home = manager_home(db, house, report)
    return render(
        request,
        "dashboard.html",
        costing=costing,
        wines=wines,
        invoices=invoices,
        house=house,
        home=home,
        report=report,
        days=window,
        counts=catalog_counts(db),
        charts=charts,
        page="home",
    )


@router.get("/dashboard")
def dashboard_redirect():
    return RedirectResponse("/", status_code=303)


@router.get("/finance")
def finance_page(
    request: Request,
    period: str = "month",
    view: str = "overview",
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    chosen = finance_view(view)
    kind, first, last = finance_period(period, start, end, earliest=earliest_finance_date(db))
    board = finance_board(db, first, last)
    sales = sales_report(db, first, last)
    vendors = vendor_report(db, first, last)
    charts = {**board["charts"], **sales["charts"], **vendors["charts"]}
    health = data_health(db, first, last, board)
    return render(
        request,
        "finance.html",
        board=board,
        sales=sales,
        vendors=vendors,
        charts=charts,
        health=health,
        period=kind,
        view=chosen,
        queries={
            "overview": finance_query(kind, "overview", first, last),
            "sales": finance_query(kind, "sales", first, last),
            "vendors": finance_query(kind, "vendors", first, last),
        },
        page="finance",
    )


@router.get("/labor")
def labor_page(request: Request):
    return render(request, "labor.html", page="labor")


@router.get("/drinks")
def drinks_page(
    request: Request,
    period: str = "month",
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    kind, first, last = finance_period(period, start, end, earliest=earliest_finance_date(db))
    return render(
        request,
        "drinks.html",
        cards=drinks_overview(db, first, last),
        period=kind,
        start=first,
        end=last,
        page="drinks",
        drink="",
    )


@router.get("/drinks/{slug}")
def drink_page(
    slug: str,
    request: Request,
    period: str = "month",
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    spec = drink_spec(slug)
    if spec is None:
        return RedirectResponse("/drinks", status_code=303)
    kind, first, last = finance_period(period, start, end, earliest=earliest_finance_date(db))
    board = drink_board(db, slug, first, last)
    wines = wine_rows(db) if slug == "wine" else []
    return render(
        request,
        "drink.html",
        drink=board,
        wines=wines,
        period=kind,
        start=first,
        end=last,
        slugs=DRINK_ORDER,
        page=slug,
    )


@router.get("/intelligence")
def intelligence_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "intelligence.html", report=overnight_report(db), page="intelligence")


@router.get("/documents")
def documents_page(request: Request):
    paperless_url = settings.paperless_public_url or "http://100.116.48.120:8011"
    return render(request, "documents.html", paperless_url=paperless_url, page="documents")


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


@router.get("/house")
def house_page(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    return render(
        request,
        "house.html",
        board=house_board(db),
        flash_ok=ok,
        flash_err=err,
        page="house",
    )


@router.get("/house/cameras")
def house_cameras_page(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    return render(
        request,
        "house_cameras.html",
        board=house_board(db),
        flash_ok=ok,
        flash_err=err,
        page="cameras",
    )


@router.post("/house/reading")
def house_reading(
    fridge_id: int = Form(...),
    temp: str = Form(...),
    unit: str = Form("f"),
    humidity: str = Form(""),
    db: Session = Depends(get_db),
):
    fridge = db.get(Fridge, fridge_id)
    if fridge is None:
        return RedirectResponse("/house", status_code=303)
    degrees = to_fahrenheit(temp if unit != "c" else None, temp if unit == "c" else None)
    if degrees is None:
        return RedirectResponse("/house", status_code=303)
    record_reading(db, fridge, degrees, humidity=humidity or None, source="manual")
    return RedirectResponse("/house", status_code=303)


@router.post("/house/camera/{camera_id}")
def house_camera(
    camera_id: int,
    snapshot_url: str = Form(""),
    stream_url: str = Form(""),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if camera:
        camera.snapshot_url = safe_http_url(snapshot_url)
        camera.stream_url = safe_http_url(stream_url)
        db.commit()
    return RedirectResponse("/house/cameras", status_code=303)


@router.get("/inventory")
def inventory(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    return render(
        request,
        "inventory.html",
        locations=COUNT_LOCATIONS,
        counts=recent_counts(db),
        flash_ok=ok,
        flash_err=err,
        page="inventory",
    )


@router.get("/inventory/names")
def inventory_names(request: Request, q: str = "", db: Session = Depends(get_db)):
    wines = wine_rows(db)
    needle = q.strip().lower()
    if needle:
        wines = [
            row
            for row in wines
            if needle in row["product"].name.lower()
            or needle in (row["product"].notes or "").lower()
            or needle in (row["profile"].color or "").lower()
        ]
    return render(request, "inventory_names.html", wines=wines, q=q.strip(), page="inventory")


@router.get("/inventory/count")
def inventory_count_sheet(request: Request, location: str = "walk-in", q: str = "", db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    sheet = count_sheet(db, location, q)
    return render(
        request,
        "inventory_count.html",
        sheet=sheet,
        locations=COUNT_LOCATIONS,
        flash_ok=ok,
        flash_err=err,
        page="inventory",
    )


@router.post("/inventory/count")
async def inventory_count_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    location = str(form.get("location") or "walk-in")
    notes = str(form.get("notes") or "Shelf count")
    raw = {}
    for key, value in form.items():
        if not str(key).startswith("qty_"):
            continue
        try:
            raw[int(str(key)[4:])] = str(value)
        except ValueError:
            continue
    result = save_count(db, location, raw, notes)
    if result.get("ok"):
        _flash(request, ok=f"Saved {result['saved']} counted items.")
        return RedirectResponse(f"/inventory/counts/{result['count_id']}", status_code=303)
    _flash(request, err="Type a number on at least one item. Blank lines are skipped.")
    suffix = f"?location={location}"
    return RedirectResponse(f"/inventory/count{suffix}", status_code=303)


@router.get("/inventory/counts/{count_id}")
def inventory_count_view(count_id: int, request: Request, db: Session = Depends(get_db)):
    detail = count_detail(db, count_id)
    if detail is None:
        return RedirectResponse("/inventory", status_code=303)
    ok, err = _pop_flash(request)
    return render(
        request,
        "inventory_count_detail.html",
        detail=detail,
        flash_ok=ok,
        flash_err=err,
        page="inventory",
    )


@router.get("/costing")
def costing_page(request: Request, days: int = DEFAULT_DAYS, db: Session = Depends(get_db)):
    window, start, end = _period(days)
    costing = period_costing(db, start, end)
    wines = wine_rows(db)
    counts = catalog_counts(db)
    activity = daily_activity(db, start, end)
    charts = dashboard_charts(costing, activity)
    return render(
        request,
        "costing.html",
        costing=costing,
        wines=wines,
        days=window,
        counts=counts,
        charts=charts,
        health=data_health(db, start.date(), end.date()),
        page="costing",
    )


@router.get("/costing/match")
def costing_match(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    rows = suggest_matches(db)
    recipes = db.query(Recipe).order_by(Recipe.name).limit(80).all()
    wines = db.query(Product).filter(Product.category == "wine").order_by(Product.name).limit(80).all()
    return render(
        request,
        "costing_match.html",
        rows=rows,
        recipes=recipes,
        wines=wines,
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


@router.post("/costing/match/link")
def costing_match_link(
    request: Request,
    item_id: int = Form(...),
    target: str = Form(...),
    db: Session = Depends(get_db),
):
    kind, _, raw = target.partition(":")
    try:
        target_id = int(raw)
    except ValueError:
        _flash(request, err="Pick a recipe or a wine.")
        return RedirectResponse("/costing/match", status_code=303)
    result = link_sellable(db, item_id, kind, target_id)
    if result.get("ok"):
        _flash(request, ok=f"Linked {result['item']} to a {result['kind']}.")
    else:
        _flash(request, err=result.get("error") or "Could not link that item.")
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
    filed_total = db.scalar(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.invoice_type.in_(PURCHASE_INVOICE_TYPES),
            Invoice.total > 0,
            Invoice.total <= INVOICE_TOTAL_MAX,
        )
    ) or 0
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
        page="invoices",
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
def purchasing_page(
    request: Request,
    category: str = "",
    days: int = DEFAULT_COMPARE_DAYS,
    view: str = "",
    db: Session = Depends(get_db),
):
    ok, err = _pop_flash(request)
    chosen = category if category in CATEGORIES else ""
    window = days if days in COMPARE_DAYS else DEFAULT_COMPARE_DAYS
    chosen_view = view if view in ("", "opportunities") else ""
    board = purchasing_board(db, chosen, days=window, view=chosen_view)
    relevant = relevant_products(db, mode="refresh")
    return render(
        request,
        "purchasing.html",
        board=board,
        categories=CATEGORIES,
        compare_days=COMPARE_DAYS,
        catalogs=catalog_lexicon(db),
        collectors=collector_rows(),
        source_label=source_label,
        market=HOME_MARKET,
        playwright_ready=playwright_available(),
        relevant_count=len(relevant),
        sams_connected=connection_status(db, "sams-club") == "connected",
        flash_ok=ok,
        flash_err=err,
        page="purchasing",
    )


@router.post("/purchasing/scan")
def purchasing_scan(
    request: Request,
    mode: str = Form("refresh"),
    days: int = Form(DEFAULT_COMPARE_DAYS),
    category: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        chosen = "discovery" if mode == "discovery" else "refresh"
        catalogs = scan_catalogs(db, mode=chosen)
        external = scan_external_prices(db)
        listed = int(catalogs.get("quotes") or 0) + int(external.get("quotes") or 0)
        skipped = len(catalogs.get("skipped") or [])
        label = "Discovery" if chosen == "discovery" else "Daily refresh"
        _flash(
            request,
            ok=(
                f"{label}: {listed} listed pack(s) for {catalogs.get('relevant') or 0} item(s) you buy. "
                f"{skipped} source(s) stay on receipts/extension (Sam's/Costco are not crawled)."
            ),
        )
    except Exception:  # noqa: BLE001
        _flash(request, err="Collector scan failed. Public catalogs and APIs are tried; club sites still need the Chrome extension.")
    window = days if days in COMPARE_DAYS else DEFAULT_COMPARE_DAYS
    chosen_cat = category if category in CATEGORIES else ""
    suffix = f"?days={window}"
    if chosen_cat:
        suffix += f"&category={chosen_cat}"
    return RedirectResponse(f"/purchasing{suffix}", status_code=303)


def collector_failure_message(status_code: int, body: str) -> str:
    text = (body or "").strip()
    lowered = text.lower()
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("error"):
                return str(data["error"])[:300]
        except Exception:  # noqa: BLE001
            pass
    if "<html" in lowered or "internal server error" in lowered:
        return "The Unraid Chromium collector failed to open the browser."
    return text[:200] or f"Collector error ({status_code})"


def _collector_json(method: str, path: str, payload: dict | None = None, timeout: float = 20.0):
    if not settings.collector_url:
        return None, "The Unraid Chromium collector is not running."
    try:
        with httpx.Client(timeout=timeout) as client:
            url = f"{settings.collector_url.rstrip('/')}{path}"
            if method == "GET":
                response = client.get(url)
            else:
                response = client.post(url, json=payload or {})
            if not response.is_success:
                return None, collector_failure_message(response.status_code, response.text)
            try:
                return response.json(), None
            except Exception:  # noqa: BLE001
                return None, "Collector returned a non-JSON response."
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:200]


@router.get("/collector")
def collector_page(request: Request, db: Session = Depends(get_db)):
    ok, err = _pop_flash(request)
    health, _health_err = _collector_json("GET", "/health", timeout=3.0)
    browsers = []
    for slug, label in BROWSER_SOURCES:
        row = browser_status_for(db, slug)
        row["label"] = label
        row["needs_login"] = slug not in PUBLIC_BROWSER_SLUGS
        browsers.append(row)
    return render(
        request,
        "collector.html",
        page="collector",
        collectors=collector_rows(),
        market=HOME_MARKET,
        near=NEAR_MILES,
        far=FAR_MILES,
        playwright_ready=bool(health and health.get("ok")),
        cellar_url=settings.resto_public_url,
        cellar_api_key=settings.resto_api_key,
        relevant=watch_payload(db),
        sams_connected=connection_status(db, "sams-club") == "connected",
        browsers=browsers,
        report=overnight_report(db),
        collector_online=bool(health and health.get("ok")),
        vnc_url=settings.collector_vnc_url,
        flash_ok=ok,
        flash_err=err,
    )


@router.post("/collector/login/{slug}")
def collector_login_start(slug: str, request: Request):
    body, err = _collector_json("POST", "/login/start", {"slug": slug}, timeout=90.0)
    if err or not (body or {}).get("ok"):
        _flash(request, err=err or (body or {}).get("error") or "Could not open Chromium.")
        return RedirectResponse("/collector", status_code=303)
    return RedirectResponse(f"/collector/session/{slug}", status_code=303)


@router.get("/collector/session/{slug}")
def collector_session(slug: str, request: Request):
    ok, err = _pop_flash(request)
    label = next((name for key, name in BROWSER_SOURCES if key == slug), slug)
    return render(
        request,
        "collector_session.html",
        page="collector",
        slug=slug,
        label=label,
        vnc_url=settings.collector_vnc_url,
        flash_ok=ok,
        flash_err=err,
    )


@router.post("/collector/login/{slug}/done")
def collector_login_done(slug: str, request: Request, db: Session = Depends(get_db)):
    from app.intel import set_browser_status

    body, err = _collector_json("POST", "/login/finish", timeout=60.0)
    if err:
        _flash(request, err=err)
        return RedirectResponse("/collector", status_code=303)
    set_browser_status(db, slug, "ready" if (body or {}).get("profile") else "never_logged_in")
    _flash(request, ok=f"{slug} browser profile saved. Nightly 02:00 will reuse it until the site asks you to log in again.")
    return RedirectResponse("/collector", status_code=303)


@router.post("/collector/scan")
def collector_scan_now(request: Request):
    body, err = _collector_json("POST", "/jobs/scan", timeout=15.0)
    if err:
        _flash(request, err=err)
    else:
        _flash(request, ok="Overnight check started. It only looks up products you already buy.")
    return RedirectResponse("/collector", status_code=303)

