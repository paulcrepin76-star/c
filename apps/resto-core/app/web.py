from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.costing import money
from app.db import get_db
from app.models import Connector, Invoice, Product, SellableItem, StockMove, WineProfile
from app.services import period_costing, wine_rows

router = APIRouter()


def render(request: Request, template: str, **context):
    return request.app.state.templates.TemplateResponse(request, template, context)


def _period(days: int = 7) -> tuple[datetime, datetime]:
    end = datetime.now(UTC).replace(tzinfo=None)
    return end - timedelta(days=days), end


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    start, end = _period(7)
    costing = period_costing(db, start, end)
    wines = wine_rows(db)
    cellar_value = money(sum((row["cellar_value"] for row in wines), Decimal(0)))
    below_par = [row for row in wines if row["below_par"]]
    connectors = db.query(Connector).order_by(Connector.name).all()
    invoices = db.query(Invoice).order_by(Invoice.issued_on.desc()).limit(6).all()
    return render(
        request,
        "dashboard.html",
        costing=costing,
        wines=wines,
        cellar_value=cellar_value,
        below_par=below_par,
        connectors=connectors,
        invoices=invoices,
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
def costing_page(request: Request, db: Session = Depends(get_db)):
    start, end = _period(7)
    costing = period_costing(db, start, end)
    wines = wine_rows(db)
    return render(request, "costing.html", costing=costing, wines=wines, page="costing")


@router.get("/invoices")
def invoices_page(request: Request, db: Session = Depends(get_db)):
    invoices = (
        db.query(Invoice)
        .options(joinedload(Invoice.supplier), joinedload(Invoice.lines))
        .order_by(Invoice.issued_on.desc())
        .all()
    )
    return render(request, "invoices.html", invoices=invoices, page="invoices")


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


@router.get("/setup")
def setup_page(request: Request):
    return render(request, "setup.html", page="setup")
